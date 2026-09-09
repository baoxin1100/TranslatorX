from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class LayoutMode(StrEnum):
    BELOW = "below"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class OcrItem:
    box: tuple[tuple[float, float], ...]
    text: str
    confidence: float
    translation: str = ""


@dataclass(slots=True)
class TranslatorConfig:
    engine: str
    source_language: str
    target_language: str
    credentials: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "credentials": dict(self.credentials),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslatorConfig":
        return cls(
            engine=str(data["engine"]),
            source_language=str(data["source_language"]),
            target_language=str(data["target_language"]),
            credentials={str(k): str(v) for k, v in data.get("credentials", {}).items()},
        )
