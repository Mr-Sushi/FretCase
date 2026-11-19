"""File storage under FRETCASE_DATA: songs with their history, assets, shares, location.

Layout::

    songs/<id>/song.json            current song
    songs/<id>/meta.json            history, undo stack, take state, card preview fingerprint
    songs/<id>/revisions/<n>.json   the song as it was at revision n
    assets/<id>.bin  assets/<id>.json
    shares/<shareId>.json           {"songId": ...}
    location.json
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fretcase_server.errors import ApiError, not_found

UNDO_LIMIT = 50


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Store:
    def __init__(self, root: Path, clock: Callable[[], str] = utc_now, drafts_ttl_hours: float = 24.0):
        self.root = Path(root)
        self.clock = clock
        self.drafts_ttl_hours = drafts_ttl_hours
        self.lock = threading.RLock()
        for sub in ("songs", "assets", "shares", "study", "prints"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- songs
    def song_dir(self, song_id: str) -> Path:
        return self.root / "songs" / song_id

    def song_exists(self, song_id: str) -> bool:
        return (self.song_dir(song_id) / "song.json").exists()

    def load_song(self, song_id: str) -> Dict[str, Any]:
        path = self.song_dir(song_id) / "song.json"
        if "/" in song_id or "\\" in song_id or not path.exists():
            raise not_found("song")
        song = _read_json(path)
        if self.is_draft(song) and self._age_hours(song) > self.drafts_ttl_hours:
            self.delete_song(song_id)
            raise not_found("song")
        return song

    def load_meta(self, song_id: str) -> Dict[str, Any]:
        path = self.song_dir(song_id) / "meta.json"
        if path.exists():
            return _read_json(path)
        return {"history": [], "undo": [], "takes": {}, "preview": None}

    def create_song(self, song: Dict[str, Any], action: str = "create", meta_extra: Optional[Dict[str, Any]] = None) -> None:
        with self.lock:
            d = self.song_dir(song["id"])
            _write_json(d / "song.json", song)
            _write_json(d / "revisions" / f"{song['revision']}.json", song)
            _write_json(d / "meta.json", {"history": [{"revision": song["revision"], "at": song["updatedAt"], "action": action}], "undo": [], "takes": {}, "preview": None, **(meta_extra or {})})

    # ---------------------------------------------------------------- drafts (candidates)
    @staticmethod
    def is_draft(song: Dict[str, Any]) -> bool:
        return bool(song.get("candidate")) and not song["candidate"].get("chosen")

    def _age_hours(self, song: Dict[str, Any]) -> float:
        def parse(text: str) -> datetime:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))

        return (parse(self.clock()) - parse(song["createdAt"])).total_seconds() / 3600.0

    def delete_song(self, song_id: str) -> None:
        import shutil

        with self.lock:
            if "/" not in song_id and "\\" not in song_id and self.song_dir(song_id).exists():
                shutil.rmtree(self.song_dir(song_id))

    def purge_drafts(self, ttl_hours: float = 24.0) -> None:
        """Delete drafts that were not chosen within ``ttl_hours``."""
        with self.lock:
            for d in list((self.root / "songs").iterdir()):
                path = d / "song.json"
                if path.exists():
                    song = _read_json(path)
                    if self.is_draft(song) and self._age_hours(song) > ttl_hours:
                        self.delete_song(d.name)

    def drafts_of_group(self, group_id: str) -> List[Dict[str, Any]]:
        out = []
        for d in (self.root / "songs").iterdir():
            path = d / "song.json"
            if path.exists():
                song = _read_json(path)
                if (song.get("candidate") or {}).get("groupId") == group_id:
                    out.append(song)
        return sorted(out, key=lambda s: s["candidate"]["index"])

    def list_songs(self) -> List[Dict[str, Any]]:
        self.purge_drafts(self.drafts_ttl_hours)
        rows = []
        for d in (self.root / "songs").iterdir():
            path = d / "song.json"
            if path.exists():
                song = _read_json(path)
                if self.is_draft(song):
                    continue
                row = {"id": song["id"], "title": song["title"], "updatedAt": song["updatedAt"]}
                if song.get("card"):
                    row["card"] = song["card"]
                rows.append(row)
        rows.sort(key=lambda r: r["updatedAt"], reverse=True)
        return rows

    def change(
        self,
        song_id: str,
        base_revision: int,
        action: str,
        fn: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]],
        undoable: bool = True,
        reset_takes: bool = True,
    ) -> Dict[str, Any]:
        """Apply ``fn(song, meta) -> new song`` as one revision. ``fn`` works on copies; it may edit ``meta``."""
        import copy

        with self.lock:
            current = self.load_song(song_id)
            if base_revision != current["revision"]:
                raise ApiError(409, "revision_conflict", f"Song is at revision {current['revision']}", song=current)
            meta = self.load_meta(song_id)
            meta_work = copy.deepcopy(meta)
            new = fn(copy.deepcopy(current), meta_work)
            new["revision"] = current["revision"] + 1
            new["updatedAt"] = self.clock()
            meta = meta_work
            if undoable:
                meta["undo"].append(current["revision"])
                meta["undo"] = meta["undo"][-UNDO_LIMIT:]
            if reset_takes:
                meta["takes"] = {}
            meta["history"].append({"revision": new["revision"], "at": new["updatedAt"], "action": action})
            self._commit(new, meta)
            return new

    def undo(self, song_id: str, base_revision: int) -> Dict[str, Any]:
        with self.lock:
            current = self.load_song(song_id)
            if base_revision != current["revision"]:
                raise ApiError(409, "revision_conflict", f"Song is at revision {current['revision']}", song=current)
            meta = self.load_meta(song_id)
            if not meta["undo"]:
                from fretcase_server.errors import cannot_apply

                raise cannot_apply("There is nothing left to undo")
            target = meta["undo"].pop()
            restored = _read_json(self.song_dir(song_id) / "revisions" / f"{target}.json")
            # a printed card stays printed
            printed = (current.get("card") or {}).get("printedAt")
            if printed and restored.get("card"):
                restored["card"]["printedAt"] = printed
            restored["revision"] = current["revision"] + 1
            restored["updatedAt"] = self.clock()
            meta["takes"] = {}
            meta["history"].append({"revision": restored["revision"], "at": restored["updatedAt"], "action": "undo"})
            self._commit(restored, meta)
            return restored

    def _commit(self, song: Dict[str, Any], meta: Dict[str, Any]) -> None:
        d = self.song_dir(song["id"])
        _write_json(d / "revisions" / f"{song['revision']}.json", song)
        _write_json(d / "song.json", song)
        _write_json(d / "meta.json", meta)

    def update_meta(self, song_id: str, fn: Callable[[Dict[str, Any]], None]) -> None:
        with self.lock:
            meta = self.load_meta(song_id)
            fn(meta)
            _write_json(self.song_dir(song_id) / "meta.json", meta)

    # ---------------------------------------------------------------- assets
    def save_asset(self, data: bytes, info: Dict[str, Any]) -> Dict[str, Any]:
        asset_id = new_id("a")
        info = {**info, "id": asset_id}
        (self.root / "assets" / f"{asset_id}.bin").write_bytes(data)
        _write_json(self.root / "assets" / f"{asset_id}.json", info)
        return info

    def asset_info(self, asset_id: str) -> Dict[str, Any]:
        path = self.root / "assets" / f"{asset_id}.json"
        if "/" in asset_id or "." in asset_id or not path.exists():
            raise not_found("asset")
        return _read_json(path)

    def asset_path(self, asset_id: str) -> Path:
        self.asset_info(asset_id)
        return self.root / "assets" / f"{asset_id}.bin"

    @staticmethod
    def public_asset(info: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("id", "role", "mime", "durationSec", "width", "height")
        return {k: info[k] for k in keys if info.get(k) is not None}

    # ---------------------------------------------------------------- shares and location
    def reserve_share(self, song_id: str) -> str:
        share_id = secrets.token_urlsafe(9)  # 12 characters of [A-Za-z0-9_-]
        _write_json(self.root / "shares" / f"{share_id}.json", {"songId": song_id})
        return share_id

    def resolve_share(self, share_id: str) -> str:
        path = self.root / "shares" / f"{share_id}.json"
        if "/" in share_id or "." in share_id or not path.exists():
            raise not_found("share")
        return _read_json(path)["songId"]

    def load_location(self) -> Dict[str, Any]:
        path = self.root / "location.json"
        return _read_json(path) if path.exists() else {"city": None, "source": "none"}

    def save_location(self, data: Dict[str, Any]) -> None:
        _write_json(self.root / "location.json", data)
