from __future__ import annotations

import json
import os
import sqlite3
import time
import tomllib
from pathlib import Path

import httpx

from .input import write_json

BASE_URL = "https://api.relayrouter.ai/v1"
MODEL = "gpt-6.1-sol"


def response_schema(schema: dict) -> dict:
    """Adapt only the API schema; local validation retains uniqueness rules."""
    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        # Property names are data, not schema keywords.
        return {
            key: {name: convert(child) for name, child in item.items()}
            if key in ("properties", "$defs") else convert(item)
            for key, item in value.items() if key != "uniqueItems"
        }
    return convert(schema)


def load_api_key() -> str:
    if os.environ.get("LIVE_CLIP_API_KEY"):
        return os.environ["LIVE_CLIP_API_KEY"]
    db = Path(os.environ.get("LIVE_CLIP_CC_SWITCH_DB", str(Path.home() / ".cc-switch/cc-switch.db")))
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as con:
        rows = con.execute("SELECT settings_config FROM providers WHERE app_type='codex' ORDER BY is_current DESC, id").fetchall()
    for (raw,) in rows:
        config = json.loads(raw)
        settings = tomllib.loads(config.get("config", ""))
        if any(p.get("base_url", "").rstrip("/") == BASE_URL for p in settings.get("model_providers", {}).values()):
            key = config.get("auth", {}).get("OPENAI_API_KEY")
            if isinstance(key, str) and key:
                os.environ.setdefault("LIVE_CLIP_API_KEY", key)
                return key
    raise ValueError("API_CREDENTIALS: CC Switch has no relayrouter Codex credential; set LIVE_CLIP_API_KEY")


class ModelClient:
    def __init__(self, key: str, *, client: httpx.Client | None = None):
        self.key = key
        self.client = client or httpx.Client(timeout=httpx.Timeout(300, connect=20))

    def request(self, prompt: str, schema: dict, evidence: Path, *, max_output_tokens: int = 8000) -> dict:
        payload = {"model": MODEL, "store": False, "input": prompt,
                   "max_output_tokens": max_output_tokens,
                   "text": {"format": {"type": "json_schema", "name": "clip_decision", "strict": True, "schema": response_schema(schema)}}}
        write_json(evidence.with_name(evidence.name + "-request.json"), payload)
        start = time.monotonic()
        try:
            response = self.client.post(BASE_URL + "/responses", headers={"Authorization": "Bearer " + self.key}, json=payload)
            if response.status_code >= 400:
                raise ValueError(f"API_HTTP_{response.status_code}: {response.text.replace(self.key, '<redacted>')[:1000]}")
            raw = response.json()
            # Whitelist response metadata and message text, excluding internal proxy metadata.
            safe = {k: raw.get(k) for k in ("id", "status", "model", "usage", "incomplete_details", "error")}
            chunks = [c.get("text", "") for item in raw.get("output", []) if item.get("type") == "message"
                      for c in item.get("content", []) if c.get("type") == "output_text"]
            if not chunks and isinstance(raw.get("output_text"), str):
                chunks = [raw["output_text"]]
            if not chunks:
                raise ValueError("API_EMPTY_OUTPUT: response contained no output text")
            safe.update(text="".join(chunks), elapsed_seconds=round(time.monotonic() - start, 3))
            write_json(evidence.with_name(evidence.name + "-response.json"), safe)
            if raw.get("status") != "completed":
                raise ValueError(f"API_INCOMPLETE: {raw.get('status')}")
            if raw.get("model") != MODEL:
                raise ValueError(f"API_MODEL_MISMATCH: {raw.get('model')}")
            result = json.loads(safe["text"])
            if not isinstance(result, dict):
                raise ValueError("API_JSON: object required")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            message = str(exc).replace(self.key, "<redacted>")
            write_json(evidence.with_name(evidence.name + "-error.json"), {"error": message, "elapsed_seconds": round(time.monotonic() - start, 3)})
            raise ValueError(message) from None

    def close(self):
        self.client.close()
