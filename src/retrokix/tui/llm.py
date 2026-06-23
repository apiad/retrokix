"""Minimal OpenAI-style chat-completions client for the Hints panel.

Works against OpenRouter or any OpenAI-compatible endpoint (e.g. a local
LM Studio server). Config merges env over ``~/.retrokix/llm.json``; the API
key is optional (local servers need none) and never committed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

DEFAULT_CONFIG_PATH = Path.home() / ".retrokix" / "llm.json"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"

SYSTEM_PROMPT = (
    "You are an expert Pokémon Emerald guide. Use ONLY the facts provided in the "
    "player's state — especially lines marked [authoritative] (next gym, type "
    "matchups, your counters). NEVER invent or contradict type effectiveness or "
    "the next gym; if a fact isn't given, don't assert it. In 2-4 sentences give "
    "concrete, correct advice: what to do next and where to go, who to "
    "train/evolve, and what type to catch to beat the next gym. No lists or "
    "headers — just the hint."
)


ASK_SYSTEM_PROMPT = (
    "You are an expert Pokémon Emerald assistant. Answer the player's question "
    "using the game state and Pokédex data provided below. Be accurate and "
    "specific; rely on the provided data and do not invent facts — especially "
    "type matchups, base stats, or evolutions. If the data doesn't cover it, say "
    "so briefly. Keep the answer to 2-5 sentences, no headers or lists."
)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    """Merge env vars over the JSON config file. Returns base_url/api_key/model
    (api_key may be None for local servers)."""
    cfg: dict = {}
    try:
        p = Path(path)
        if p.exists():
            cfg = json.loads(p.read_text())
    except Exception:
        cfg = {}
    return {
        "base_url": os.environ.get("RETROKIX_LLM_BASE_URL") or cfg.get("base_url") or DEFAULT_BASE_URL,
        "api_key": (
            os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("RETROKIX_LLM_API_KEY")
            or cfg.get("api_key")
        ),
        "model": os.environ.get("RETROKIX_HINT_MODEL") or cfg.get("model") or DEFAULT_MODEL,
    }


def generate_hint(
    prompt: str,
    config: dict,
    *,
    system: str = SYSTEM_PROMPT,
    timeout: float = 40.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """POST a chat completion and return the assistant text. Raises on HTTP error."""
    headers = {"Content-Type": "application/json"}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    url = config["base_url"].rstrip("/") + "/chat/completions"
    body = {
        "model": config["model"],
        "max_tokens": 220,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    with httpx.Client(transport=transport, timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
