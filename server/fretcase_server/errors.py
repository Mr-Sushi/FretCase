"""API errors in the shape docs/api.md defines: {"error": {"code", "message", "song"?, "detail"?}}."""
from __future__ import annotations

from typing import Any, Dict, Optional


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, song: Optional[Dict[str, Any]] = None, detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.song = song
        self.detail = detail

    def body(self) -> Dict[str, Any]:
        err: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.song is not None:
            err["song"] = self.song
        if self.detail:
            err["detail"] = self.detail
        return {"error": err}


def invalid_request(message: str, detail: Optional[Dict[str, Any]] = None) -> ApiError:
    return ApiError(400, "invalid_request", message, detail=detail)


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"Unknown {what}")


def cannot_apply(message: str, detail: Optional[Dict[str, Any]] = None) -> ApiError:
    return ApiError(422, "cannot_apply", message, detail=detail)


def not_implemented(what: str) -> ApiError:
    return ApiError(501, "not_implemented", f"{what} is not implemented in this release")


def offline_unavailable(what: str) -> ApiError:
    return ApiError(503, "offline_unavailable", f"{what} needs the network, which is not available")
