from __future__ import annotations

from typing import Any


def error_payload(code: str, message: str, detail: str = "") -> dict[str, Any]:
    return {"code": code, "message": message, "detail": detail}
