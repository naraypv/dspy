from dspy.clients.base_lm import BaseLM
from dspy.clients.subscription_lm import build_chat_response


def test_build_chat_response_matches_baselm_completion_processing():
    response = build_chat_response(
        model="subscription/codex-pro",
        text="ready",
        usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    )

    lm = BaseLM(model="subscription/codex-pro")
    assert lm._process_completion(response, {}) == ["ready"]
    assert response.model == "subscription/codex-pro"
    assert dict(response.usage) == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}


def test_build_chat_response_carries_provider_metadata():
    response = build_chat_response(
        model="subscription/cursor",
        text="ready",
        provider_metadata={"provider": "cursor", "account": "cursor-pro"},
    )

    assert response.provider_metadata == {"provider": "cursor", "account": "cursor-pro"}
