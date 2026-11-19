"""Seams for everything that would call an outside service (milestone 2). Milestone 1 ships only offline stubs.

Every adapter method is called through ``call_with_timeout`` (default 8 s) and the caller falls back to the
offline path. An adapter that has no offline path raises ``Offline`` and the API answers 503 ``offline_unavailable``.
No adapter in this release opens a network connection.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, TypeVar

T = TypeVar("T")
DEFAULT_TIMEOUT_S = 8.0


class Offline(Exception):
    """The adapter needs the network and there is none (or no provider is configured)."""


class SeedModel(Protocol):
    """Multimodal seed-card parsing (photos, text, sounds) by a model."""

    def analyse(self, inputs: Sequence[Dict[str, Any]], assets: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]: ...


class HarmonyModel(Protocol):
    """Model-proposed chord candidates, to be scored by HRE like the library candidates."""

    def candidates(self, melody: Sequence[Dict[str, Any]], key: Dict[str, str], bars: int) -> Optional[List[List[str]]]: ...


class LyricsWriter(Protocol):
    def write(self, song: Dict[str, Any], section_id: str, note_count: int, hint: Optional[str]) -> str: ...


class VocalSynth(Protocol):
    def render(self, song: Dict[str, Any]) -> bytes: ...


class Stylizer(Protocol):
    """Model-based card stylisation. Returns PNG bytes or None to use the local filters."""

    def stylize(self, photo: bytes, style: str) -> Optional[bytes]: ...


class SongRenderer(Protocol):
    def render(self, song: Dict[str, Any]) -> bytes: ...


class Uploader(Protocol):
    def upload(self, song: Dict[str, Any], files: Dict[str, bytes]) -> str: ...


class OfflineStub:
    """Default for every adapter: nothing is available."""

    def analyse(self, *a: Any, **k: Any) -> None:
        return None

    def candidates(self, *a: Any, **k: Any) -> None:
        return None

    def stylize(self, *a: Any, **k: Any) -> None:
        return None

    def write(self, *a: Any, **k: Any) -> str:
        raise Offline("lyrics generation")

    def render(self, *a: Any, **k: Any) -> bytes:
        raise Offline("rendering")

    def upload(self, *a: Any, **k: Any) -> str:
        raise Offline("upload")

    def is_online(self) -> bool:
        return False


@dataclass
class Adapters:
    seed_model: SeedModel = field(default_factory=OfflineStub)
    harmony_model: HarmonyModel = field(default_factory=OfflineStub)
    lyrics: LyricsWriter = field(default_factory=OfflineStub)
    vocal: VocalSynth = field(default_factory=OfflineStub)
    stylizer: Stylizer = field(default_factory=OfflineStub)
    renderer: SongRenderer = field(default_factory=OfflineStub)
    uploader: Uploader = field(default_factory=OfflineStub)
    timeout_s: float = DEFAULT_TIMEOUT_S

    def online(self) -> bool:
        """Whether the server reached the internet recently. Always False until a real provider reports it."""
        probes = [getattr(a, "is_online", None) for a in (self.seed_model, self.lyrics, self.vocal, self.stylizer, self.renderer, self.uploader)]
        return any(bool(p()) for p in probes if callable(p))


_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="adapter")


def call_with_timeout(fn: Callable[..., T], *args: Any, timeout: float = DEFAULT_TIMEOUT_S, fallback: Optional[T] = None, **kwargs: Any) -> Optional[T]:
    """Run an adapter call with a timeout; any failure (including a timeout) returns ``fallback``.
    ``Offline`` is re-raised so callers without an offline path can answer 503."""
    future = _POOL.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except Offline:
        raise
    except Exception:  # timeout or provider error: use the offline path
        future.cancel()
        return fallback
