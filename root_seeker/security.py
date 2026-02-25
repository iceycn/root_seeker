from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException


def build_api_key_dependency(allowed_keys: list[str]) -> Callable[..., None]:
    allowed = set(allowed_keys)

    async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if not allowed:
            return
        if x_api_key in allowed:
            return
        raise HTTPException(status_code=401, detail="invalid api key")

    return require_api_key
