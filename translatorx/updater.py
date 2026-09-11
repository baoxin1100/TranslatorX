from __future__ import annotations

import re
from typing import Iterable

import requests

REPO_WEB_URL = "https://github.com/baoxin1100/TranslatorX"
REPO_GIT_URL = "https://cnb.cool/baoxin1100/TranslatorX"
REFS_URL = f"{REPO_GIT_URL}.git/info/refs?service=git-upload-pack"
_USER_AGENT = "TranslatorX"

_RELEASE_TAG = re.compile(r"^v?(\d+(?:\.\d+)*)$")
_TAG_PREFIX = "refs/tags/"


class UpdateCheckError(RuntimeError):
    """Raised when the remote version list cannot be read."""


def parse_release_tags(payload: bytes) -> list[str]:
    """Return release tag names advertised by a git smart-HTTP ref response."""
    tags: list[str] = []
    index = 0
    size = len(payload)
    while index + 4 <= size:
        try:
            length = int(payload[index:index + 4], 16)
        except ValueError:
            break
        if length == 0:  # flush packet
            index += 4
            continue
        if length < 4:
            break
        line = payload[index + 4:index + length]
        index += length
        text = line.decode("utf-8", "replace").split("\x00", 1)[0].strip()
        if not text or text.startswith("#"):
            continue
        _, _, ref = text.partition(" ")
        if not ref.startswith(_TAG_PREFIX) or ref.endswith("^{}"):
            continue
        name = ref[len(_TAG_PREFIX):]
        if _RELEASE_TAG.match(name):
            tags.append(name)
    return tags


def version_key(version: str | None) -> tuple[int, ...]:
    """Return a comparable tuple for a dotted version string."""
    if not version:
        return ()
    text = str(version).strip().lstrip("vV")
    parts: list[int] = []
    for part in text.split("."):
        digits = re.match(r"^\d+", part)
        if not digits:
            break
        parts.append(int(digits.group()))
    return tuple(parts)


def latest_release(tags: Iterable[str]) -> str | None:
    """Return the highest release tag, or None when there is none."""
    candidates = [tag for tag in tags if _RELEASE_TAG.match(tag)]
    if not candidates:
        return None
    return max(candidates, key=version_key)


def fetch_latest_version(timeout: float = 15.0, session: requests.Session | None = None) -> str | None:
    """Query the update repository and return its newest release tag."""
    http = session or requests
    try:
        response = http.get(
            REFS_URL,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateCheckError(str(exc)) from exc
    return latest_release(parse_release_tags(response.content))


def is_update_available(latest: str | None, current: str | None) -> bool:
    """Return True when ``latest`` is a strictly newer release than ``current``."""
    if not latest or not current:
        return False
    return version_key(latest) > version_key(current)
