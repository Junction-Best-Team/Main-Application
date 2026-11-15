"""Application diagnostics around the portable Google client; no content is logged."""

import logging
import re

from aimo.google_api import google_api_request as request
from aimo.observability import event, log_context, operation

OPERATIONS = {"generate_content", "embed_content", "decide", "list_models", "create_live_token"}
FINISH_REASONS = {
    "STOP",
    "MAX_TOKENS",
    "SAFETY",
    "RECITATION",
    "OTHER",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "MALFORMED_FUNCTION_CALL",
    "UNEXPECTED_TOOL_CALL",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "NO_IMAGE",
    "LANGUAGE",
    "IMAGE_OTHER",
    "IMAGE_RECITATION",
    "FINISH_REASON_UNSPECIFIED",
}


def enum_value(value, allowed):
    return value if isinstance(value, str) and value in allowed else "other"


def response_metadata(result):
    candidates = result.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    counts = {"functionCall": 0, "text": 0, "thought": 0, "inlineData": 0}
    finishes = []
    for candidate in candidates[:8]:
        if not isinstance(candidate, dict):
            continue
        finishes.append(enum_value(candidate.get("finishReason"), FINISH_REASONS))
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict):
                for key in counts:
                    counts[key] += key in part
    feedback = result.get("promptFeedback")
    feedback = feedback if isinstance(feedback, dict) else {}
    usage = result.get("usageMetadata")
    usage = usage if isinstance(usage, dict) else {}
    return {
        "candidate_count": len(candidates),
        "finish_reasons": finishes,
        "tool_call_count": counts["functionCall"],
        "text_part_count": counts["text"],
        "thought_part_count": counts["thought"],
        "inline_part_count": counts["inlineData"],
        "block_reason": enum_value(
            feedback.get("blockReason"),
            {
                "SAFETY",
                "OTHER",
                "BLOCKLIST",
                "PROHIBITED_CONTENT",
                "IMAGE_SAFETY",
                "BLOCK_REASON_UNSPECIFIED",
            },
        )
        if feedback.get("blockReason")
        else None,
        "usage": {
            key: usage[key]
            for key in (
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
                "thoughtsTokenCount",
                "cachedContentTokenCount",
                "toolUsePromptTokenCount",
            )
            if type(usage.get(key)) is int
        },
    }


def google_api_request(operation, **kwargs):
    model = kwargs.get("model")
    model = (
        model
        if isinstance(model, str) and re.fullmatch(r"(?:models/)?[A-Za-z0-9._-]{1,160}", model)
        else None
    )
    with log_context(
        provider="google",
        provider_operation=enum_value(operation, OPERATIONS),
        provider_model=model,
    ):
        return _request(operation, **kwargs)


@operation("provider.google")
def _request(operation, **kwargs):
    def observe(stage, fields):
        event(
            "provider.google." + stage,
            level=logging.WARNING if stage in {"body_limit", "transport_failed"} else logging.INFO,
            **fields,
        )

    result = request(operation, **kwargs, observer=observe)
    event("provider.google.result", **response_metadata(result))
    return result
