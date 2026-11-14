"""The frontend test fixtures must be valid responses of the real API.

The browser-side tests (frontend/tests) answer every request from frontend/tests/fixtures/api.json.
If a fixture drifted from what the server actually returns, those tests would pass against an API
that does not exist. Here the server's own response models validate the same JSON, so a renamed,
removed or retyped field fails this test.
"""

import json
from pathlib import Path

import pytest

from aimo.chat_schemas import ConversationList, ConversationResponse
from aimo.schemas import CommitResponse, InboxResponse, ProposalResponse, SessionResponse

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[1] / "frontend/tests/fixtures/api.json").read_text()
)

MODELS = {
    "session": SessionResponse,
    "proposal": ProposalResponse,
    "conversation_blank": ConversationResponse,
    "conversation_with_plan": ConversationResponse,
    "conversation_list": ConversationList,
    "purchase_history": InboxResponse,
    "commit_accepted": CommitResponse,
    "commit_revised": CommitResponse,
}


def test_every_fixture_is_checked():
    assert set(FIXTURES) == set(MODELS), "add the new fixture to MODELS (or delete it)"


@pytest.mark.parametrize("name", sorted(MODELS))
def test_fixture_is_a_valid_api_response(name):
    MODELS[name].model_validate(FIXTURES[name])


def test_validation_would_catch_a_drifted_fixture():
    broken = {k: v for k, v in FIXTURES["proposal"].items() if k != "policy_outcome"}
    with pytest.raises(ValueError):
        ProposalResponse.model_validate(broken)
    extra = FIXTURES["session"] | {"unexpected_field": 1}
    with pytest.raises(ValueError):
        SessionResponse.model_validate(extra)
