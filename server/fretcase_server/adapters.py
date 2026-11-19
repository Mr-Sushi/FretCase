"""Seams for everything that would call an outside service (milestone 2). Milestone 2 adds one real adapter, the text model for lyrics (``AnthropicTextModel``).

Every adapter method is called through ``call_with_timeout`` (default 8 s) and the caller falls back to the
offline path. An adapter that has no offline path raises ``Offline`` and the API answers 503 ``offline_unavailable``.
Only ``AnthropicTextModel``, and only when its environment variables are set, opens a connection.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, TypeVar

T = TypeVar("T")
DEFAULT_TIMEOUT_S = 8.0


class Offline(Exception):
    """The adapter needs the network and there is none (or no provider is configured)."""


class ModelError(Exception):
    """A model call failed. ``reason`` says why, for the API's ``error.detail.reason``:
    ``auth`` (key refused), ``rate_limited``, ``unreachable``, ``timeout`` or ``bad_answer``."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


class SeedModel(Protocol):
    """Multimodal seed-card parsing (photos, text, sounds) by a model."""

    def analyse(self, inputs: Sequence[Dict[str, Any]], assets: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]: ...


class HarmonyModel(Protocol):
    """Model-proposed chord candidates, to be scored by HRE like the library candidates."""

    def candidates(self, melody: Sequence[Dict[str, Any]], key: Dict[str, str], bars: int) -> Optional[List[List[str]]]: ...


class TextModel(Protocol):
    """One adapter for a text model (lyrics). ``complete`` returns the model's text, raises ``Offline`` when no model
    is configured and any other exception when the call fails."""

    def complete(self, system: str, prompt: str, max_tokens: int = 1500, timeout: float = 20.0) -> str: ...


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

    def complete(self, *a: Any, **k: Any) -> str:
        raise Offline("text model")

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
    text_model: TextModel = field(default_factory=OfflineStub)
    vocal: VocalSynth = field(default_factory=OfflineStub)
    stylizer: Stylizer = field(default_factory=OfflineStub)
    renderer: SongRenderer = field(default_factory=OfflineStub)
    uploader: Uploader = field(default_factory=OfflineStub)
    timeout_s: float = DEFAULT_TIMEOUT_S

    def online(self) -> bool:
        """Whether the server reached the internet recently. Always False until a real provider reports it."""
        probes = [getattr(a, "is_online", None) for a in (self.seed_model, self.text_model, self.vocal, self.stylizer, self.renderer, self.uploader)]
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


DEFAULT_TEXT_MODEL_URL = "https://api.anthropic.com"
DEFAULT_TEXT_MODEL_NAME = "claude-sonnet-5-5"


class AnthropicTextModel:
    """Text model through the Anthropic Messages API format.

    Configured by ``FRETCASE_TEXT_MODEL_KEY`` (required), ``FRETCASE_TEXT_MODEL_URL`` (the endpoint, or a base URL that
    the path /v1/messages is added to; default https://api.anthropic.com) and ``FRETCASE_TEXT_MODEL_NAME`` (default
    claude-sonnet-5-5). Without a key nothing is configured and no connection is ever opened.
    """

    ONLINE_TTL_S = 30.0

    def __init__(self, url: Optional[str], key: Optional[str], name: Optional[str]):
        self.key = key
        self.url = url or (DEFAULT_TEXT_MODEL_URL if key else None)
        self.name = name or (DEFAULT_TEXT_MODEL_NAME if key else None)
        self._online_at = -1e9
        self._probe: Optional[tuple[float, bool]] = None

    @property
    def configured(self) -> bool:
        return bool(self.url and self.key and self.name)

    def endpoint(self) -> str:
        url = (self.url or "").rstrip("/")
        return url if url.endswith("/messages") else url + "/v1/messages"

    def complete(self, system: str, prompt: str, max_tokens: int = 1500, timeout: float = 20.0) -> str:
        if not self.configured:
            raise Offline("text model")
        import json
        import socket
        import time
        import urllib.error
        import urllib.request

        body = json.dumps({"model": self.name, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint(), data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": self.key or "", "anthropic-version": "2023-06-01"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (the URL is operator configuration)
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._online_at = time.monotonic()  # the service answered, so the network is there
            if exc.code in (401, 403):
                raise ModelError("auth", f"the model service refused the key ({exc.code})") from exc
            if exc.code == 429:
                raise ModelError("rate_limited", "the model service is rate limiting") from exc
            raise ModelError("unreachable", f"the model service answered {exc.code}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ModelError("timeout", "the model did not answer in time") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ModelError("unreachable", str(exc)) from exc
        except ValueError as exc:
            raise ModelError("bad_answer", "the model service sent something that is not JSON") from exc
        self._online_at = time.monotonic()
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")

    def is_online(self) -> bool:
        """True when a call worked in the last 30 s, or a quick connection to the model host works (cached 30 s)."""
        if not self.configured:
            return False
        import socket
        import time
        from urllib.parse import urlparse

        now = time.monotonic()
        if now - self._online_at < self.ONLINE_TTL_S:
            return True
        if self._probe and now - self._probe[0] < self.ONLINE_TTL_S:
            return self._probe[1]
        parsed = urlparse(self.endpoint())
        try:
            with socket.create_connection((parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)), timeout=2.0):
                ok = True
        except OSError:
            ok = False
        self._probe = (now, ok)
        return ok
