"""Tests for the LLM client + config (mocked transport, no network)."""
from __future__ import annotations

import json

import httpx
import pytest

from retrokix.tui import llm


def test_generate_hint_returns_trimmed_text():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "m"
        assert any(m["role"] == "system" for m in body["messages"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "  Go to Slateport.  "}}]})

    cfg = {"base_url": "http://x/v1", "api_key": "k", "model": "m"}
    out = llm.generate_hint("ctx", cfg, transport=httpx.MockTransport(handler))
    assert out == "Go to Slateport."


def test_generate_hint_sends_auth_header_when_key_present():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm.generate_hint("c", {"base_url": "http://x/v1", "api_key": "secret", "model": "m"},
                      transport=httpx.MockTransport(handler))
    assert seen["auth"] == "Bearer secret"


def test_generate_hint_no_auth_header_for_local():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm.generate_hint("c", {"base_url": "http://localhost:1234/v1", "api_key": None, "model": "m"},
                      transport=httpx.MockTransport(handler))
    assert seen["auth"] is None


def test_generate_hint_raises_on_http_error():
    handler = lambda req: httpx.Response(500, text="boom")  # noqa: E731
    with pytest.raises(httpx.HTTPStatusError):
        llm.generate_hint("c", {"base_url": "http://x/v1", "api_key": "k", "model": "m"},
                          transport=httpx.MockTransport(handler))


def test_load_config_env_overrides_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "llm.json"
    cfg_file.write_text(json.dumps({"base_url": "http://file/v1", "api_key": "filekey", "model": "filemodel"}))
    monkeypatch.setenv("RETROKIX_HINT_MODEL", "envmodel")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RETROKIX_LLM_API_KEY", raising=False)
    monkeypatch.delenv("RETROKIX_LLM_BASE_URL", raising=False)

    cfg = llm.load_config(path=cfg_file)
    assert cfg["model"] == "envmodel"        # env wins
    assert cfg["base_url"] == "http://file/v1"  # file used
    assert cfg["api_key"] == "filekey"


def test_load_config_defaults_when_absent(tmp_path, monkeypatch):
    for v in ("OPENROUTER_API_KEY", "RETROKIX_LLM_API_KEY", "RETROKIX_LLM_BASE_URL", "RETROKIX_HINT_MODEL"):
        monkeypatch.delenv(v, raising=False)
    cfg = llm.load_config(path=tmp_path / "nope.json")
    assert cfg["base_url"] == llm.DEFAULT_BASE_URL
    assert cfg["model"] == llm.DEFAULT_MODEL
    assert cfg["api_key"] is None
