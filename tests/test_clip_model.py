import json

import httpx
import pytest


def test_responses_parses_output_text_and_records_safe_usage(tmp_path):
    from live_clip_studio.clips.model import ModelClient
    def respond(request):
        data = json.loads(request.content)
        assert data["model"] == "gpt-6.1-sol"
        assert data["store"] is False
        assert data["text"]["format"]["strict"] is True
        return httpx.Response(200, json={"status": "completed", "model": "gpt-6.1-sol",
            "output": [{"type": "reasoning", "summary": []}, {"type": "message", "content": [
                {"type": "output_text", "text": '{"ok":true}'}]}], "usage": {"total_tokens": 12}})
    model = ModelClient("secret-test-key", client=httpx.Client(transport=httpx.MockTransport(respond)))
    result = model.request("hello", {"type": "object"}, tmp_path / "probe")
    assert result == {"ok": True}
    evidence = (tmp_path / "probe-response.json").read_text()
    assert '"total_tokens": 12' in evidence
    assert "secret-test-key" not in "".join(p.read_text() for p in tmp_path.iterdir())


@pytest.mark.parametrize("payload", [
    {"status": "incomplete", "output": []},
    {"status": "completed", "model": "other-model", "output": []},
    {"status": "completed", "model": "gpt-6.1-sol", "output": [{"type": "message", "content": [{"type": "output_text", "text": "bad"}]}]},
])
def test_model_rejects_truncated_wrong_model_and_nonjson(payload, tmp_path):
    from live_clip_studio.clips.model import ModelClient
    m = ModelClient("secret", client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))))
    with pytest.raises(ValueError):
        m.request("hello", {}, tmp_path / "error")


def test_credentials_process_env_wins_over_cc_switch(monkeypatch):
    from live_clip_studio.clips.model import load_api_key
    monkeypatch.setenv("LIVE_CLIP_API_KEY", "opaque.key.with.$.chars")
    assert load_api_key() == "opaque.key.with.$.chars"


def test_model_sends_api_compatible_schema_without_weakening_local_contract(tmp_path):
    import copy
    from live_clip_studio.clips.contract import DECISION_SCHEMA
    from live_clip_studio.clips.model import ModelClient

    original = copy.deepcopy(DECISION_SCHEMA)

    def respond(request):
        schema = json.loads(request.content)["text"]["format"]["schema"]
        for field in ("body", "cold", "gold", "chapters"):
            assert "uniqueItems" not in schema["properties"]["clips"]["items"]["properties"][field]
        assert schema["additionalProperties"] is False
        assert schema["properties"]["clips"]["items"]["properties"]["body"]["maxItems"] == 160
        return httpx.Response(200, json={"status": "completed", "model": "gpt-6.1-sol", "output_text": '{"ok":true}'})

    client = ModelClient("secret", client=httpx.Client(transport=httpx.MockTransport(respond)))
    try:
        assert client.request("test", DECISION_SCHEMA, tmp_path / "compatibility") == {"ok": True}
    finally:
        client.close()
    assert DECISION_SCHEMA == original
    assert DECISION_SCHEMA["properties"]["clips"]["items"]["properties"]["body"]["uniqueItems"] is True
