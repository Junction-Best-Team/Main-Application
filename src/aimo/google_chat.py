"""Native Gemini adapter for the existing typed internal agent loop.

Opaque model parts, including thought signatures, are replayed within the turn
only. They never become customer messages, tool arguments, or audit content.
"""

import json
import re
from uuid import uuid4

from pydantic import ValidationError

from aimo.agent_provider import (
    MAX_CONTEXT_BYTES,
    MAX_RESPONSE_BYTES,
    AssistantReply,
    check_deadline,
    encode,
    response_rejected,
)
from aimo.attachments import image_context_bytes, model_text
from aimo.db import Problem
from aimo.google_api import GoogleAPIError, google_api_request
from aimo.observability import event, operation


class GoogleChatProvider:
    def __init__(self, config, client):
        self.config, self.client = config, client
        if not config.gemini_api_key.strip():
            raise Problem("LLM_NOT_CONFIGURED", "Configure GEMINI_API_KEY for the assistant.", 503)
        if not re.fullmatch(r"(?:models/)?gemini-[A-Za-z0-9._-]+", config.llm_model):
            raise Problem(
                "LLM_CONFIGURATION", "Set LLM_MODEL to a native Google chat model ID.", 503
            )

    @staticmethod
    def contents(messages):
        system, contents, calls = [], [], {}
        for message in messages:
            role = message["role"]
            if role == "system":
                system.append({"text": message["content"]})
                continue
            if role == "tool":
                name, provider_id = calls[message["tool_call_id"]]
                result = json.loads(message["content"])
                response = {
                    "name": name,
                    "response": result if isinstance(result, dict) else {"result": result},
                }
                if provider_id:
                    response["id"] = provider_id
                parts = [{"functionResponse": response}]
                native_role = "user"
            elif role == "assistant":
                native_role = "model"
                parts = message.get("google_parts")
                if parts is None:
                    parts = [{"text": message["content"]}] if message.get("content") else []
                    parts += [
                        {
                            "functionCall": {
                                "name": c["function"]["name"],
                                "args": json.loads(c["function"]["arguments"]),
                            }
                        }
                        for c in message.get("tool_calls", [])
                    ]
                native_calls = [p["functionCall"] for p in parts if "functionCall" in p]
                for call, native in zip(message.get("tool_calls", []), native_calls, strict=True):
                    calls[call["id"]] = (call["function"]["name"], native.get("id"))
            else:
                native_role, parts = "user", [{"text": message["content"]}]
                for item in message.get("attachments", []):
                    parts.append({"text": model_text(item)})
                    if item.get("image_data"):
                        parts.append(
                            {"inlineData": {"mimeType": "image/jpeg", "data": item["image_data"]}}
                        )
            if parts:
                if contents and contents[-1]["role"] == native_role:
                    contents[-1]["parts"].extend(parts)
                else:
                    contents.append({"role": native_role, "parts": list(parts)})
        return system, contents

    @operation("llm.completion")
    def complete(self, messages, tools, deadline):
        system, contents = self.contents(messages)
        generation = {"maxOutputTokens": self.config.llm_max_completion_tokens}
        if self.config.llm_reasoning_effort:
            generation["thinkingConfig"] = {
                "thinkingLevel": self.config.llm_reasoning_effort.upper()
            }
        payload = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": system}
        if tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t["function"]["name"],
                            "description": t["function"].get("description", ""),
                            "parametersJsonSchema": t["function"]["parameters"],
                        }
                        for t in tools
                    ]
                }
            ]
            payload["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        image_bytes = image_context_bytes(messages)
        if len(encode(payload).encode()) - image_bytes > MAX_CONTEXT_BYTES or image_bytes > 6_000_000:
            raise Problem(
                "LLM_CONTEXT_LIMIT", "Start a new conversation; the assistant context is full.", 422
            )
        try:
            result = google_api_request(
                "generate_content",
                model=self.config.llm_model,
                api_key=self.config.gemini_api_key,
                client=self.client,
                payload=payload,
                timeout=min(self.config.llm_timeout_seconds, check_deadline(deadline)),
                max_response_bytes=MAX_RESPONSE_BYTES,
            )
        except GoogleAPIError as exc:
            if exc.code == "TIMEOUT":
                raise Problem(
                    "LLM_TIMEOUT", "The assistant reached its time limit. Retry this message.", 504
                ) from None
            code = "LLM_CONFIGURATION" if exc.code == "AUTH_REJECTED" else "LLM_UNAVAILABLE"
            raise Problem(
                code, "Google could not complete the assistant request. Retry later.", 503
            ) from None
        check_deadline(deadline)
        data = result if isinstance(result, dict) else {}
        usage = data.get("usageMetadata", {})
        usage = usage if isinstance(usage, dict) else {}
        candidates = data.get("candidates")
        candidate = candidates[0] if isinstance(candidates, list) and candidates else {}
        candidate = candidate if isinstance(candidate, dict) else {}
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        finish = candidate.get("finishReason")
        event(
            "llm.result",
            model=self.config.llm_model,
            finish_reason=finish if finish in (
                "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "BLOCKLIST",
                "PROHIBITED_CONTENT", "SPII", "MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", None,
            ) else "other",
            tool_call_count=sum(isinstance(p, dict) and "functionCall" in p for p in parts)
            if isinstance(parts, list) else None,
            usage={
                k: usage[k]
                for k in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")
                if type(usage.get(k)) is int
            },
        )
        return self.parse(result)

    @staticmethod
    def parse(result):
        category = "shape"
        try:
            candidate = result["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                category = "incomplete"
                raise ValueError("Incomplete response")
            parts = candidate["content"]["parts"]
            text, calls = [], []
            for part in parts:
                if "functionCall" in part:
                    call = part["functionCall"]
                    arguments = call.get("args", {})
                    if not isinstance(arguments, dict):
                        category = "arguments"
                        raise ValueError("Invalid arguments")
                    calls.append(
                        {
                            "id": call.get("id") or uuid4().hex,
                            "type": "function",
                            "function": {"name": call["name"], "arguments": encode(arguments)},
                        }
                    )
                elif "text" in part and not part.get("thought"):
                    text.append(part["text"])
                elif not part.get("thought"):
                    category = "modality"
                    raise ValueError("Unexpected modality")
            if not text and not calls:
                category = "empty"
                raise ValueError("Empty response")
            return AssistantReply(
                content="".join(text) or None, tool_calls=calls, google_parts=parts
            )
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, ValidationError) as exc:
            response_rejected(exc, category)
            raise Problem(
                "LLM_RESPONSE_INVALID",
                "Google returned an invalid or incomplete response. Retry later.",
                502,
            ) from None
