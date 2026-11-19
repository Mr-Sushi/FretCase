"""FastAPI application: the HTTP API of docs/api.md and the panel WebSocket."""
from __future__ import annotations

import copy
import io
import json
import mimetypes
import os
import signal
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import ValidationError

from fretcase_engine import editing, export, generate
from fretcase_engine.common import TRACKS
from fretcase_engine.generate import CannotApply
from fretcase_engine.rhythm import load_presets
from fretcase_engine.song_model import Note, Song as SongModel, VocalNote
from fretcase_server import cards, hum, seed_analysis
from fretcase_server.adapters import Adapters, Offline, call_with_timeout
from fretcase_server.config import VERSION, Settings
from fretcase_server.errors import ApiError, cannot_apply, invalid_request, not_found, not_implemented, offline_unavailable
from fretcase_server.panel import PanelHub
from fretcase_server.schemas import (
    AnotherRequest,
    CreateSongRequest,
    EditRequest,
    LocationRequest,
    RehumRequest,
    RevisionRequest,
    SeedRequest,
    StudyLogRequest,
)
from fretcase_server.store import Store, new_id

CATALOG_INSTRUMENTS = {
    "vocal": ["synth-female", "synth-male"],
    "melody": ["piano", "nylon-lead"],
    "guitar": ["nylon", "steel"],
    "bass": ["finger-bass"],
    "drums": ["brush-kit", "pop-kit"],
    "ambience": ["recording"],
}
CARD_STYLES = ["ink", "comic", "xieyi", "original", "text"]
ASSET_ROLES = {"hum", "ambience", "photo", "vocal_take"}
PHOTO_ROLES = {"photo"}


def validate_song(song: Dict[str, Any]) -> Dict[str, Any]:
    """Check a song against the Pydantic model generated from the schema and the rules the schema cannot express."""
    try:
        SongModel.model_validate(song)
    except ValidationError as exc:  # a bug in generation, not a client error
        raise RuntimeError(f"Generated an invalid song: {exc}") from exc
    problems = editing.check_consistency(song)
    if problems:
        raise RuntimeError(f"Generated an inconsistent song: {problems}")
    return song


def create_app(
    settings: Optional[Settings] = None,
    adapters: Optional[Adapters] = None,
    card_module_loader: Optional[Callable[[], Any]] = None,
    printer_factory: Optional[Callable[[Any], Any]] = None,
    hum_transcriber: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    on_shutdown: Optional[Callable[[], None]] = None,
    clock: Optional[Callable[[], str]] = None,
) -> FastAPI:
    settings = settings or Settings()
    adapters = adapters or Adapters(timeout_s=settings.http_timeout_s)
    store = Store(settings.data_dir, **({"clock": clock} if clock else {}))
    hub = PanelHub()
    load_cards = card_module_loader or cards.load_card_module
    transcribe = hum_transcriber or hum.transcribe
    app = FastAPI(title="FretCase", version=VERSION)
    app.state.store, app.state.hub, app.state.adapters = store, hub, adapters

    # ------------------------------------------------------------------ errors
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(exc.body(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        first = errors[0] if errors else {"loc": [], "msg": "invalid"}
        err = invalid_request(f"{'.'.join(first['loc'])}: {first['msg']}", {"errors": errors[:10]})
        return JSONResponse(err.body(), status_code=400)

    # ------------------------------------------------------------------ helpers
    def song_response(song: Dict[str, Any]) -> Dict[str, Any]:
        return {"song": song}

    def finish(song: Dict[str, Any]) -> Dict[str, Any]:
        return validate_song(song)

    def changed(song_id: str, base: int, action: str, fn: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]], **kw: Any) -> Dict[str, Any]:
        def wrapped(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            try:
                return finish(fn(song, meta))
            except CannotApply as exc:
                raise cannot_apply(exc.message, exc.detail) from exc

        return song_response(store.change(song_id, base, action, wrapped, **kw))

    def asset_in_song(song: Dict[str, Any], asset_id: str, role_ok: Optional[set] = None) -> Dict[str, Any]:
        info = store.asset_info(asset_id)
        if role_ok and info["role"] not in role_ok:
            raise cannot_apply(f"Asset {asset_id} has role {info['role']}", {"assetId": asset_id})
        if not any(a["id"] == asset_id for a in song["assets"]):
            song["assets"].append(store.public_asset(info))
        return info

    # ------------------------------------------------------------------ status and catalogue
    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "online": adapters.online(), "version": VERSION, "panel": hub.panel_connected}

    @app.get("/api/catalog")
    def catalog() -> Dict[str, Any]:
        return {"instruments": CATALOG_INSTRUMENTS, "rhythmPresets": load_presets(), "cardStyles": CARD_STYLES}

    # ------------------------------------------------------------------ assets
    @app.post("/api/assets")
    async def post_asset(file: UploadFile = File(...), role: str = Form(...)) -> Dict[str, Any]:
        if role not in ASSET_ROLES:
            raise invalid_request(f"role must be one of {sorted(ASSET_ROLES)}")
        data = await file.read()
        if not data:
            raise invalid_request("The file is empty")
        if len(data) > settings.max_upload_bytes:
            raise invalid_request("The file is too large")
        mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
        info: Dict[str, Any] = {"role": role, "mime": mime}
        if role in ("hum", "ambience", "vocal_take"):
            duration = audio_duration(data, mime)
            if duration is not None:
                info["durationSec"] = round(duration, 2)
        elif role == "photo":
            size = image_size(data)
            if size:
                info["width"], info["height"] = size
        return {"asset": store.public_asset(store.save_asset(data, info))}

    @app.get("/api/assets/{asset_id}")
    def get_asset(asset_id: str) -> Response:
        info = store.asset_info(asset_id)
        return FileResponse(store.asset_path(asset_id), media_type=info["mime"])

    # ------------------------------------------------------------------ seed
    @app.post("/api/seed")
    def post_seed(body: SeedRequest) -> Dict[str, Any]:
        inputs = []
        for item in body.inputs:
            d = item.model_dump(mode="json", exclude_none=True)
            if d["kind"] == "text":
                if not d.get("text"):
                    raise invalid_request("A text input needs text")
            else:
                if not d.get("assetId"):
                    raise invalid_request(f"A {d['kind']} input needs assetId")
                info = store.asset_info(d["assetId"])
                expected = {"hum": {"hum"}, "sound": {"ambience"}, "photo": {"photo"}}[d["kind"]]
                if info["role"] not in expected:
                    raise invalid_request(f"Asset {d['assetId']} has role {info['role']}, not usable as {d['kind']}")
            inputs.append(d)
        assets = {i["assetId"]: store.asset_info(i["assetId"]) for i in inputs if i.get("assetId")}
        modelled = call_with_timeout(adapters.seed_model.analyse, inputs, assets, timeout=adapters.timeout_s, fallback=None)
        if modelled:
            modelled["source"] = "model"
            return {"seed": modelled}

        def loader(asset_id: str):
            return store.asset_info(asset_id), store.asset_path(asset_id)

        seed = seed_analysis.build_seed(inputs, loader, transcribe=transcribe)
        return {"seed": seed}

    # ------------------------------------------------------------------ songs
    @app.post("/api/songs", status_code=201)
    def create_song(body: CreateSongRequest) -> Dict[str, Any]:
        seed = body.seed.model_dump(mode="json", exclude_none=True)
        assets = []
        for item in seed["inputs"]:
            if item.get("assetId"):
                assets.append(store.public_asset(store.asset_info(item["assetId"])))
        now = store.clock()
        song = generate.generate_song(seed, new_id("song"), now, bars=body.bars, assets=assets)
        location = store.load_location()
        photo = next((i["assetId"] for i in seed["inputs"] if i["kind"] == "photo"), None)
        card: Dict[str, Any] = {"style": "ink" if photo else "text", "showPhoto": False, "showCity": False}
        if photo:
            card["photoAssetId"] = photo
            card["capturedAt"] = now
        if location.get("city"):
            card["city"] = location["city"]
        song["card"] = card
        song = finish(song)
        store.create_song(song)
        if location.get("source") == "manual":  # a typed place applies to one song
            store.save_location({"city": None, "source": "none"})
        return song_response(song)

    @app.get("/api/songs")
    def list_songs() -> Dict[str, Any]:
        return {"songs": store.list_songs()}

    @app.get("/api/songs/{song_id}")
    def get_song(song_id: str) -> Dict[str, Any]:
        return song_response(store.load_song(song_id))

    @app.post("/api/songs/{song_id}/edits")
    def post_edits(song_id: str, body: EditRequest) -> Dict[str, Any]:
        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            for op in body.ops:
                song = apply_op(song, op, meta)
            return song

        names = "+".join(op.op for op in body.ops)
        return changed(song_id, body.baseRevision, names, apply)

    def apply_op(song: Dict[str, Any], op: Any, meta: Dict[str, Any]) -> Dict[str, Any]:
        name = op.op
        if name == "setControl":
            song["controls"][op.control] = op.value
            return generate.apply_density(song) if op.control == "density" else generate.reharmonise(song)
        if name == "setTempo":
            song["tempo"] = op.tempo
            return song
        if name == "setTrackVolume":
            song["tracks"][op.track]["volume"] = op.volume
            return song
        if name == "setTrackMute":
            song["tracks"][op.track]["muted"] = op.muted
            return song
        if name == "setInstrument":
            if op.instrument not in CATALOG_INSTRUMENTS[op.track]:
                raise CannotApply(f"{op.instrument!r} is not an instrument of the {op.track} track", {"track": op.track, "instrument": op.instrument})
            song["tracks"][op.track]["instrument"] = op.instrument
            return song
        if name == "replaceNotes":
            note_model = VocalNote if op.track == "vocal" else Note
            try:
                notes = [note_model.model_validate(n).model_dump(mode="json", exclude_unset=True) for n in op.notes]
            except ValidationError as exc:
                raise invalid_request(f"A note is not valid: {exc.errors()[0]['msg']}", {"errors": [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()[:5]]}) from exc
            return editing.replace_notes(song, op.track, op.from_, op.to, notes)
        if name == "setLyrics":
            return editing.set_lyrics(song, op.section, op.text)
        if name == "setRhythm":
            return generate.set_rhythm(song, op.family, op.presetId)
        if name == "lock":
            return editing.lock(song, op.track, op.section)
        if name == "unlock":
            return editing.unlock(song, op.track, op.section)
        if name == "setSections":
            return editing.set_sections(song, [s.model_dump(mode="json") for s in op.sections])
        if name == "setTitle":
            song["title"] = op.title
            return song
        if name == "setCard":
            card = song.setdefault("card", {"style": "text", "showPhoto": False, "showCity": False})
            for field in op.model_fields_set - {"op"}:
                value = getattr(op, field)
                if field == "photoAssetId" and value is not None:
                    asset_in_song(song, value, PHOTO_ROLES)
                if value is None and field not in ("style", "showPhoto", "showCity"):
                    card.pop(field, None)
                elif value is not None:
                    card[field] = value
            return song
        if name == "setVocalTake":
            raise not_implemented("Using your own vocal recording")
        raise invalid_request(f"Unknown op {name}")

    @app.post("/api/songs/{song_id}/another")
    def post_another(song_id: str, body: AnotherRequest) -> Dict[str, Any]:
        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            key = f"{body.section}|{body.track or '*'}"
            state = meta.setdefault("takes", {}).get(key, {})
            song, state = generate.another_take(song, body.section, body.track, state)
            meta["takes"][key] = state
            return song

        return changed(song_id, body.baseRevision, "another", apply, reset_takes=False)

    @app.post("/api/songs/{song_id}/rehum")
    def post_rehum(song_id: str, body: RehumRequest) -> Dict[str, Any]:
        info = store.asset_info(body.assetId)
        if info["role"] != "hum":
            raise cannot_apply("The asset is not a hum recording", {"assetId": body.assetId})
        current = store.load_song(song_id)
        result = transcribe(store.asset_path(body.assetId), float(current["tempo"]))
        if result is None:
            raise cannot_apply("Hum transcription is not available on this device", {"assetId": body.assetId, "reason": "no_transcriber"})
        notes = result["motif"]

        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            asset_in_song(song, body.assetId)
            return generate.rehum(song, body.section, notes)

        return changed(song_id, body.baseRevision, "rehum", apply)

    @app.post("/api/songs/{song_id}/undo")
    def post_undo(song_id: str, body: RevisionRequest) -> Dict[str, Any]:
        return song_response(store.undo(song_id, body.baseRevision))

    @app.get("/api/songs/{song_id}/history")
    def get_history(song_id: str) -> Dict[str, Any]:
        store.load_song(song_id)
        return {"history": list(reversed(store.load_meta(song_id)["history"]))}

    @app.post("/api/songs/{song_id}/lyrics")
    def post_lyrics(song_id: str) -> Any:
        raise not_implemented("Writing lyrics")

    @app.post("/api/songs/{song_id}/vocal")
    def post_vocal(song_id: str) -> Any:
        raise not_implemented("Vocal synthesis")

    @app.post("/api/songs/{song_id}/share")
    def post_share(song_id: str) -> Any:
        raise not_implemented("Uploading the song page")

    @app.get("/api/songs/{song_id}/export")
    def get_export(song_id: str, format: str = "midi") -> Response:
        song = store.load_song(song_id)
        if format == "midi":
            return Response(export.to_midi(song), media_type="audio/midi", headers={"Content-Disposition": f'attachment; filename="{song_id}.mid"'})
        if format == "musicxml":
            return Response(export.to_musicxml(song), media_type="application/vnd.recordare.musicxml+xml", headers={"Content-Disposition": f'attachment; filename="{song_id}.musicxml"'})
        if format == "abc":
            return Response(export.to_abc(song), media_type="text/vnd.abc; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{song_id}.abc"'})
        raise invalid_request("format must be midi, musicxml or abc")

    # ------------------------------------------------------------------ cards
    @app.post("/api/songs/{song_id}/card/preview")
    def card_preview(song_id: str, body: RevisionRequest) -> Dict[str, Any]:
        module = load_cards()

        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            card = song.setdefault("card", {"style": "text", "showPhoto": False, "showCity": False})
            if not card.get("share"):
                share_id = store.reserve_share(song["id"])
                card["share"] = {"shareId": share_id, "url": f"{settings.share_base_url.rstrip('/')}/s/{share_id}", "state": "reserved"}
            photo_path = None
            if card.get("photoAssetId") and card["style"] != "text":
                photo_path = store.asset_path(card["photoAssetId"])
            try:
                images = module.render_card(cards.card_input(module, song, photo_path))
            except Exception as exc:
                raise cannot_apply(f"The card could not be rendered: {exc}") from exc
            song["assets"] = [a for a in song["assets"] if a["role"] not in ("card_front", "card_back", "card_print")]
            ids = {}
            for role, data in (("card_front", images.front_png), ("card_back", images.back_png), ("card_print", images.strip_png)):
                info = store.save_asset(data, {"role": role, "mime": "image/png"})
                ids[role] = info["id"]
                asset_in_song(song, info["id"])
            card["frontAssetId"], card["backAssetId"] = ids["card_front"], ids["card_back"]
            meta["preview"] = {"fingerprint": cards.card_fingerprint(song), "stripAssetId": ids["card_print"]}
            return song

        return changed(song_id, body.baseRevision, "card/preview", apply)

    @app.post("/api/songs/{song_id}/card/print")
    def card_print(song_id: str, body: RevisionRequest) -> Dict[str, Any]:
        module = load_cards()

        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            card = song.get("card") or {}
            preview = meta.get("preview")
            if not card.get("frontAssetId") or not preview or preview["fingerprint"] != cards.card_fingerprint(song):
                raise cannot_apply("There is no preview of the current card; preview it first", {"reason": "no_preview"})
            printer = make_printer(module)
            try:
                printer.print_strip(store.asset_path(preview["stripAssetId"]).read_bytes())
            except module.PrinterError as exc:
                raise cannot_apply(f"The printer reported an error: {exc}", {"printer": str(exc)}) from exc
            card["printedAt"] = store.clock()
            return song

        return changed(song_id, body.baseRevision, "card/print", apply, undoable=False)

    def make_printer(module: Any) -> Any:
        if printer_factory:
            return printer_factory(module)
        if settings.printer_device:
            return module.Printer(device=settings.printer_device)
        return module.Printer(dry_run_dir=settings.data_dir / "prints")

    @app.get("/api/share/{share_id}")
    def get_share(share_id: str) -> Dict[str, Any]:
        song_id = store.resolve_share(share_id)  # raises 404 for an unknown card
        return {"songId": song_id}

    # ------------------------------------------------------------------ location
    @app.get("/api/location")
    def get_location() -> Dict[str, Any]:
        loc = store.load_location()
        return {"city": loc.get("city"), "source": loc.get("source", "none") if loc.get("city") else "none"}

    @app.put("/api/location")
    def put_location(body: LocationRequest) -> Dict[str, Any]:
        store.save_location({"city": body.city.strip(), "source": "manual"})
        return get_location()

    # ------------------------------------------------------------------ jobs (nothing runs as a job in this release)
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> Any:
        raise not_found("job")

    # ------------------------------------------------------------------ system
    @app.post("/api/system/shutdown", status_code=202)
    def shutdown(background: BackgroundTasks) -> Dict[str, Any]:
        flush_study()
        background.add_task(on_shutdown or default_shutdown)
        return {"ok": True}

    def default_shutdown() -> None:
        if os.environ.get("FRETCASE_NO_EXIT"):
            return
        os.kill(os.getpid(), signal.SIGTERM)

    study_lock = threading.Lock()

    def study_path() -> Path:
        return store.root / "study" / f"{store.clock()[:10]}.jsonl"

    def flush_study() -> None:
        # events are appended and closed per request, so there is nothing buffered; kept as the shutdown hook
        return None

    @app.post("/api/study/log")
    def study_log(body: StudyLogRequest) -> Dict[str, Any]:
        with study_lock:
            with study_path().open("a", encoding="utf-8") as fh:
                for event in body.events:
                    fh.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
        return {"ok": True, "count": len(body.events)}

    # ------------------------------------------------------------------ panel
    @app.websocket("/ws/panel")
    async def ws_panel(ws: WebSocket) -> None:
        await hub.handle(ws)

    return app


def audio_duration(data: bytes, mime: str) -> Optional[float]:
    """Duration in seconds: WAV directly, anything else through ffprobe when it is installed."""
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except (wave.Error, EOFError):
        pass
    import subprocess
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".bin") as tmp:
            tmp.write(data)
            tmp.flush()
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", tmp.name],
                capture_output=True, text=True, timeout=20,
            )
        return float(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def image_size(data: bytes) -> Optional[tuple]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.size
    except Exception:
        return None
