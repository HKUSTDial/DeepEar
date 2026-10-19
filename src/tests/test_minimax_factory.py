import json

import httpx
import pytest
from agno.models.message import Message

from src.utils.llm.factory import get_model


@pytest.fixture
def minimax_request(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
    monkeypatch.delenv("MINIMAX_THINKING", raising=False)
    monkeypatch.delenv("MINIMAX_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("MINIMAX_REGION", "global_en")

    def invoke(model_id, **kwargs):
        requests = []

        def handle_request(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "test-completion",
                    "object": "chat.completion",
                    "created": 0,
                    "model": model_id,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handle_request)) as client:
            model = get_model("minimax", model_id, http_client=client, **kwargs)
            model.invoke(
                [Message(role="user", content="Hello")], Message(role="assistant")
            )

        assert len(requests) == 1
        return requests[0], json.loads(requests[0].content)

    return invoke


@pytest.mark.parametrize(
    ("model_id", "mode", "expected_mode"),
    [
        ("MiniMax-M3.1-Flash", None, "adaptive"),
        ("MiniMax-M3.1-Flash", "adaptive", "adaptive"),
        ("MiniMax-M3.1-Flash", "disabled", "adaptive"),
        ("MiniMax-M3.1-Flash", "invalid", "adaptive"),
        ("MiniMax-M3", None, "adaptive"),
        ("MiniMax-M3", "adaptive", "adaptive"),
        ("MiniMax-M3", "disabled", "disabled"),
        ("MiniMax-M3", "invalid", "adaptive"),
        ("custom-model", "disabled", "disabled"),
    ],
)
def test_minimax_thinking_request(
    monkeypatch, minimax_request, model_id, mode, expected_mode
):
    if mode is not None:
        monkeypatch.setenv("MINIMAX_THINKING", mode)
    _, body = minimax_request(model_id)
    assert body["model"] == model_id
    assert "enable_thinking" not in body
    assert body["thinking"] == {"type": expected_mode}
    if model_id == "MiniMax-M3.1-Flash":
        assert body["reasoning_effort"] == "max"
    else:
        assert "reasoning_effort" not in body


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
@pytest.mark.parametrize("source", ["environment", "argument"])
def test_flash_effort(monkeypatch, minimax_request, effort, source):
    monkeypatch.setenv(
        "MINIMAX_REASONING_EFFORT", effort if source == "environment" else "low"
    )
    kwargs = {"reasoning_effort": effort} if source == "argument" else {}
    _, body = minimax_request("MiniMax-M3.1-Flash", **kwargs)
    assert body["reasoning_effort"] == effort
    assert body["thinking"] == {"type": "adaptive"}


@pytest.mark.parametrize("effort", ["none", "invalid", ""])
def test_invalid_flash_effort_falls_back_to_max(monkeypatch, minimax_request, effort):
    monkeypatch.setenv("MINIMAX_REASONING_EFFORT", effort)
    _, body = minimax_request("MiniMax-M3.1-Flash")
    assert body["reasoning_effort"] == "max"


def test_m3_does_not_use_flash_effort_setting(monkeypatch, minimax_request):
    monkeypatch.setenv("MINIMAX_REASONING_EFFORT", "low")
    _, body = minimax_request("MiniMax-M3")
    assert "reasoning_effort" not in body


@pytest.mark.parametrize(
    ("region", "override", "expected"),
    [
        ("global_en", None, "https://api.minimax.io/v1/chat/completions"),
        ("cn_zh", None, "https://api.minimaxi.com/v1/chat/completions"),
        (
            "global_en",
            "https://example.com/v1",
            "https://example.com/v1/chat/completions",
        ),
    ],
)
def test_minimax_region_and_custom_endpoint(
    monkeypatch, minimax_request, region, override, expected
):
    monkeypatch.setenv("MINIMAX_REGION", region)
    if override is not None:
        monkeypatch.setenv("MINIMAX_BASE_URL", override)
    request, _ = minimax_request("MiniMax-M3.1-Flash")
    assert str(request.url) == expected
