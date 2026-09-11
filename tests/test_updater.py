from __future__ import annotations

import pytest

from translatorx import updater


def _pkt(text: str) -> bytes:
    payload = text.encode("utf-8")
    return ("%04x" % (len(payload) + 4)).encode("ascii") + payload


def _refs(*tags: str, branch: str = "main") -> bytes:
    chunks = [
        _pkt("# service=git-upload-pack\n"),
        b"0000",
        _pkt("a" * 40 + f" refs/heads/{branch}\n"),
    ]
    for tag in tags:
        chunks.append(_pkt("b" * 40 + f" refs/tags/{tag}\n"))
        chunks.append(_pkt("c" * 40 + f" refs/tags/{tag}^{{}}\n"))
    chunks.append(b"0000")
    return b"".join(chunks)


def test_parse_release_tags_skips_peeled_and_prerelease():
    payload = _refs("v1.0.6", "v1.0.7", "v0.1.1-beta.1", "v0.1.1-beta.2")
    assert updater.parse_release_tags(payload) == ["v1.0.6", "v1.0.7"]


def test_parse_release_tags_handles_capability_suffix_on_first_ref():
    payload = (
        _pkt("# service=git-upload-pack\n")
        + b"0000"
        + _pkt("a" * 40 + " refs/heads/main\x00multi_ack thin-pack\n")
        + _pkt("d" * 40 + " refs/tags/v2.0.0\n")
        + b"0000"
    )
    assert updater.parse_release_tags(payload) == ["v2.0.0"]


def test_latest_release_picks_highest_numeric_version():
    assert updater.latest_release(["v1.0.9", "v1.0.10", "v1.0.2"]) == "v1.0.10"
    assert updater.latest_release(["v0.1.1-beta.1"]) is None
    assert updater.latest_release([]) is None


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("v1.0.7", (1, 0, 7)),
        ("1.2", (1, 2)),
        ("", ()),
        (None, ()),
    ],
)
def test_version_key(version, expected):
    assert updater.version_key(version) == expected


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("v1.0.8", "v1.0.7", True),
        ("v1.0.7", "v1.0.7", False),
        ("v1.0.6", "v1.0.7", False),
        ("v1.0.10", "v1.0.9", True),
        ("", "v1.0.7", False),
        ("v1.0.8", "", False),
        (None, None, False),
    ],
)
def test_is_update_available(latest, current, expected):
    assert updater.is_update_available(latest, current) is expected


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[str] = []

    def get(self, url, timeout=None, headers=None):  # noqa: ANN001, ANN201
        self.calls.append(url)
        return _FakeResponse(self.content)


def test_fetch_latest_version_uses_remote_refs():
    session = _FakeSession(_refs("v1.0.5", "v1.0.6"))
    assert updater.fetch_latest_version(session=session) == "v1.0.6"
    assert session.calls == [updater.REFS_URL]


def test_fetch_latest_version_wraps_request_errors():
    class _Boom:
        def get(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
            raise updater.requests.RequestException("offline")

    with pytest.raises(updater.UpdateCheckError):
        updater.fetch_latest_version(session=_Boom())
