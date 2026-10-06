"""Shared cursor-pagination helper (dashboard F1).

Jobs'ta kullanılan cursor/limit/total kalıbı burada tekilleşir;
applications ve documents aynı encode/decode + Page şemasını kullanır.
Bozuk cursor 422 döner (500 değil).
"""

import base64
import json
from typing import Generic, TypeVar

from fastapi import HTTPException
from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None
    total: int


def encode_cursor(*parts) -> str:
    return base64.urlsafe_b64encode(json.dumps(parts, default=str).encode()).decode()


def decode_cursor(cursor: str, n: int) -> list:
    try:
        parts = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(parts, list) or len(parts) != n:
            raise ValueError
        return parts
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid cursor.")


def escape_like(value: str) -> str:
    """Kaçırır: % ve _ (ve kaçış karakteri) LIKE kalıbı olmaktan çıkar."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
