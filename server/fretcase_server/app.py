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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import ValidationError

from fretcase_engine import candidates as cand_engine
from fretcase_engine import catalog as catalog_data
from fretcase_engine import editing, export, generate
from fretcase_engine import regions as regions_engine
from fretcase_engine.common import TRACKS
from fretcase_engine.generate import CannotApply
from fretcase_engine.rhythm import load_presets
from fretcase_engine.song_model import Note, Song as SongModel, VocalNote
from fretcase_server import cards, hum, lyrics, seed_analysis
from fretcase_server.adapters import Adapters, AnthropicTextModel, Offline, call_with_timeout
from fretcase_server.config import VERSION, Settings
from fretcase_server.errors import ApiError, cannot_apply, invalid_request, not_found, not_implemented, offline_unavailable
from fretcase_server.panel import PanelHub
from fretcase_server.schemas import (
    AlternativesRequest,
    AnotherRequest,
    CandidatesRequest,
    ChooseRequest,
    CreateSongRequest,
    EditRequest,
    LocationRequest,
    LyricsRequest,
    RehumRequest,
    RevisionRequest,
    SeedRequest,
    StudyLogRequest,
)
from fretcase_server.store import Store, new_id

CARD_STYLES = catalog_data.CARD_STYLES
ASSET_ROLES = {"hum", "ambience", "photo", "vocal_take"}
PHOTO_ROLES = {"photo"}
MAX_PHOTOS = 9
MAX_PHOTO_SIDE = 4096


def check_photo_limit(inputs: List[Dict[str, Any]]) -> None:
    if sum(1 for i in inputs if i.get("kind") == "photo") > MAX_PHOTOS:
        raise invalid_request(f"At most {MAX_PHOTOS} photos are allowed")


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
    adapters = adapters or Adapters(
        text_model=AnthropicTextModel(settings.text_model_url, settings.text_model_key, settings.text_model_name),
        timeout_s=settings.http_timeout_s,
    )
    store = Store(settings.data_dir, drafts_ttl_hours=settings.drafts_ttl_hours, **({"clock": clock} if clock else {}))
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
        return {**catalog_data.catalog(), "rhythmPresets": load_presets()}

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
            data, mime = scale_photo(data, mime)
            info["mime"] = mime
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
        check_photo_limit([i.model_dump(mode="json") for i in body.inputs])
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
    def seed_assets(seed: Dict[str, Any]) -> List[Dict[str, Any]]:
        check_photo_limit(seed["inputs"])
        return [store.public_asset(store.asset_info(i["assetId"])) for i in seed["inputs"] if i.get("assetId")]

    def default_card(seed: Dict[str, Any], now: str) -> Dict[str, Any]:
        """xieyi with photos, text without; the cover is the first photo; every photo is shown on the song page."""
        photos = [i["assetId"] for i in seed["inputs"] if i["kind"] == "photo"]
        card: Dict[str, Any] = {"style": "xieyi" if photos else "text", "showPhoto": False, "showCity": False, "capturedAt": now}
        if photos:
            card["photoAssetIds"] = photos
            card["coverAssetId"] = photos[0]
        city = store.load_location().get("city")
        if city:
            card["city"] = city
        return card

    def apply_texts(song: Dict[str, Any], texts: Dict[str, str]) -> Dict[str, Any]:
        for section_id, text in texts.items():
            song = editing.set_lyrics(song, section_id, text)
        return song

    @app.post("/api/songs", status_code=201)
    def create_song(body: CreateSongRequest) -> Dict[str, Any]:
        seed = body.seed.model_dump(mode="json", exclude_none=True)
        assets = seed_assets(seed)
        now = store.clock()
        song = generate.generate_song(seed, new_id("song"), now, bars=body.bars, assets=assets)
        song["card"] = default_card(seed, now)
        try:
            song = apply_texts(song, lyrics.initial_texts(adapters, song))
        except CannotApply:
            pass  # the model's lines did not fit after all: keep the placeholder syllables
        song = finish(song)
        store.create_song(song)
        if store.load_location().get("source") == "manual":  # a typed place applies to one song
            store.save_location({"city": None, "source": "none"})
        return song_response(song)

    @app.post("/api/candidates", status_code=201)
    def post_candidates(body: CandidatesRequest) -> Dict[str, Any]:
        store.purge_drafts(settings.drafts_ttl_hours)
        seed = body.seed.model_dump(mode="json", exclude_none=True)
        assets = seed_assets(seed)
        avoid = []
        if body.previousGroupId:
            avoid = [cand_engine.song_signature(d) for d in store.drafts_of_group(body.previousGroupId)]
        now = store.clock()
        group_id = new_id("grp")
        ids = [new_id("song") for _ in range(3)]
        made = cand_engine.make_candidates(seed, ids, group_id, now, bars=body.bars, time_of_day=body.timeOfDay, avoid=avoid, assets=assets)
        out = []
        for song, lead_state in made:
            song["card"] = default_card(seed, now)
            song = finish(song)
            store.create_song(song, "candidate", meta_extra={"lead": lead_state})
            out.append(song)
        return {"candidates": out}

    @app.post("/api/songs/{song_id}/choose")
    def choose(song_id: str, body: Optional[ChooseRequest] = None) -> Dict[str, Any]:
        song = store.load_song(song_id)
        if not song.get("candidate"):
            raise cannot_apply("This song is not a candidate", {"songId": song_id})
        if song["candidate"].get("chosen"):
            return song_response(song)
        try:
            texts = lyrics.initial_texts(adapters, song)
        except Exception:  # noqa: BLE001
            texts = {}

        def apply(current: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            try:
                current = apply_texts(current, texts)
            except CannotApply:
                pass
            current["candidate"]["chosen"] = True
            return current

        chosen = store.change(song_id, song["revision"], "choose", lambda sg, meta: finish(apply(sg, meta)), undoable=False)
        for sibling in store.drafts_of_group(chosen["candidate"]["groupId"]):
            if sibling["id"] != song_id and store.is_draft(sibling):
                store.delete_song(sibling["id"])
        if store.load_location().get("source") == "manual":
            store.save_location({"city": None, "source": "none"})
        return song_response(chosen)

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

    def set_card(song: Dict[str, Any], op: Any) -> Dict[str, Any]:
        card = song.setdefault("card", {"style": "text", "showPhoto": False, "showCity": False})
        sent = op.model_fields_set - {"op"}
        for field in sent:
            value = getattr(op, field)
            if field == "photoAssetIds":
                ids = value or []
                if len(set(ids)) != len(ids):
                    raise CannotApply("photoAssetIds must not repeat a photo", {"photoAssetIds": ids})
                for asset_id in ids:
                    asset_in_song(song, asset_id, PHOTO_ROLES)
                card["photoAssetIds"] = ids
            elif field == "coverAssetId":
                continue  # checked below, once the photo list is final
            elif value is None and field not in ("style", "showPhoto", "showCity"):
                card.pop(field, None)
            elif value is not None:
                card[field] = value
        ids = card.get("photoAssetIds") or []
        if "coverAssetId" in sent and op.coverAssetId is not None:
            if op.coverAssetId not in ids:
                raise CannotApply("coverAssetId must be one of photoAssetIds", {"coverAssetId": op.coverAssetId})
            card["coverAssetId"] = op.coverAssetId
        elif "coverAssetId" in sent:
            card.pop("coverAssetId", None)
        if card["style"] == "text":
            card.pop("coverAssetId", None)
        elif card.get("coverAssetId") not in ids:
            card.pop("coverAssetId", None)
            if ids:
                card["coverAssetId"] = ids[0]
        # any card change makes the previewed image stale: print needs a new preview
        card.pop("frontAssetId", None)
        return song

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
            if op.instrument not in catalog_data.instrument_ids(op.track):
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
            return editing.set_sections(song, [s.model_dump(mode="json", exclude_none=True) for s in op.sections])
        if name == "setTitle":
            song["title"] = op.title
            if song.get("card"):
                song["card"].pop("frontAssetId", None)  # the title is printed on the card
            return song
        if name == "setCard":
            return set_card(song, op)
        if name == "setRegion":
            return editing.set_region(song, op.track, op.section, op.play, op.complexity, op.intensity, op.style)
        if name == "copyRegion":
            return editing.copy_region(song, op.track, op.section)
        if name == "setLead":
            song, state = editing.set_lead(song, op.section, op.track, meta.get("lead") or {})
            meta["lead"] = state
            return song
        if name == "shiftRegister":
            return editing.shift_register(song, op.track, op.section, op.direction)
        if name == "revertMelody":
            return editing.revert_melody(song, op.section)
        if name == "setMaster":
            return editing.set_master(song, op.volume, op.space)
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
    def post_lyrics(song_id: str, body: LyricsRequest) -> Dict[str, Any]:
        song = store.load_song(song_id)
        if song["revision"] != body.baseRevision:
            raise ApiError(409, "revision_conflict", f"Song is at revision {song['revision']}", song=song)
        known = {x["id"] for x in song["sections"]}
        for sid in list(body.sections or []) + list((body.keep or {}).keys()):
            if sid not in known:
                raise cannot_apply("Unknown section", {"section": sid})
        # the model call runs outside the store lock; a stale revision is caught again when the result is stored
        texts = lyrics.write_lyrics(adapters, song, body.sections, body.keep, body.themes, body.tone, body.rhyme)
        if not texts:
            raise cannot_apply("There are no lyric lines to rewrite", {"reason": "nothing_to_write"})

        def apply(current: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            return apply_texts(current, texts)

        return changed(song_id, body.baseRevision, "lyrics", apply)

    @app.post("/api/songs/{song_id}/lyrics/alternatives")
    def post_lyrics_alternatives(song_id: str, body: AlternativesRequest) -> Dict[str, Any]:
        song = store.load_song(song_id)
        section = next((x for x in song["sections"] if x["id"] == body.section), None)
        if section is None:
            raise cannot_apply("Unknown section", {"section": body.section})
        return {"alternatives": lyrics.alternatives(adapters, song, section, body.line, body.themes, body.tone, body.rhyme)}

    @app.get("/api/songs/{song_id}/lyrics/themes")
    def get_lyrics_themes(song_id: str) -> Dict[str, Any]:
        return {"themes": lyrics.themes(store.load_song(song_id))}

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
    def share_base(request: Request) -> str:
        return (settings.share_base_url or str(request.base_url)).rstrip("/")

    @app.post("/api/songs/{song_id}/card/preview")
    def card_preview(song_id: str, body: RevisionRequest, request: Request) -> Dict[str, Any]:
        module = load_cards()
        base = share_base(request)

        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            card = song.setdefault("card", {"style": "text", "showPhoto": False, "showCity": False})
            cover_path = None
            if card["style"] != "text":
                if not card.get("coverAssetId"):
                    raise cannot_apply("Pick a cover photo for this card style", {"reason": "no_cover"})
                cover_path = store.asset_path(card["coverAssetId"])
            if not card.get("share"):
                share_id = store.reserve_share(song["id"])
                card["share"] = {"shareId": share_id, "url": f"{base}/s/{share_id}", "state": "reserved"}
            try:
                images = module.render_card(cards.card_input(module, song, cover_path))
            except (ValueError, OSError) as exc:
                raise cannot_apply(f"The card could not be rendered: {exc}") from exc
            old = [a["id"] for a in song["assets"] if a["role"] == "card_print"]
            song["assets"] = [a for a in song["assets"] if a["role"] != "card_print"]
            info = store.save_asset(images.print_png, {"role": "card_print", "mime": "image/png", "width": 1260, "height": 840})
            song["assets"].append(store.public_asset(info))
            card["frontAssetId"] = info["id"]
            meta["preview"] = {"fingerprint": cards.card_fingerprint(song), "assetId": info["id"], "replaced": old}
            return song

        return changed(song_id, body.baseRevision, "card/preview", apply)

    @app.post("/api/songs/{song_id}/card/print")
    def card_print(song_id: str, body: RevisionRequest) -> Dict[str, Any]:
        module = load_cards()

        def apply(song: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
            card = song.get("card") or {}
            preview = meta.get("preview")
            if not card.get("frontAssetId") or not preview or preview["fingerprint"] != cards.card_fingerprint(song) or preview["assetId"] != card["frontAssetId"]:
                raise cannot_apply("There is no preview of the current card; preview it first", {"reason": "no_preview"})
            printer = make_printer(module)
            try:
                printer.print_card(store.asset_path(card["frontAssetId"]).read_bytes())
            except module.PrinterError as exc:
                raise cannot_apply(f"The printer reported an error: {exc}", {"printer": str(exc)}) from exc
            card["printedAt"] = store.clock()
            return song

        return changed(song_id, body.baseRevision, "card/print", apply, undoable=False)

    def make_printer(module: Any) -> Any:
        if printer_factory:
            return printer_factory(module)
        return module.Printer(spec=settings.printer_device, dry_run_dir=settings.data_dir / "prints")

    @app.get("/api/printer")
    def get_printer() -> Dict[str, Any]:
        module = load_cards()
        try:
            status = make_printer(module).status()
        except Exception:  # noqa: BLE001 (a printer that cannot be reached is a status, not an error)
            status = {"kind": "dry_run", "connected": False, "paper": "unknown", "remaining": None}
        return {"printer": {"kind": status.get("kind", "dry_run"), "connected": bool(status.get("connected")), "paper": status.get("paper", "unknown"), "remaining": status.get("remaining")}}

    @app.get("/api/share/{share_id}")
    def get_share(share_id: str) -> Dict[str, Any]:
        song_id = store.resolve_share(share_id)  # raises 404 for an unknown card
        return {"songId": song_id}

    def page_for(share_id: str) -> Dict[str, Any]:
        song = copy.deepcopy(store.load_song(store.resolve_share(share_id)))
        card = song.get("card") or {}
        base = f"/api/share/{share_id}/assets/"
        show_photo = bool(card.get("showPhoto"))
        photo_ids = list(card.get("photoAssetIds") or []) if show_photo else []
        page: Dict[str, Any] = {"title": song["title"]}
        if (song.get("candidate") or {}).get("name"):
            page["subtitle"] = song["candidate"]["name"]
        if card.get("line"):
            page["line"] = card["line"]
        if card.get("showCity") and card.get("city"):
            page["city"] = card["city"]
        stamp = card.get("capturedAt") or song["createdAt"]
        page["date"] = stamp[:10]
        if card.get("message"):
            page["message"] = card["message"]
        page["photos"] = [base + a for a in photo_ids]
        if card.get("frontAssetId"):
            page["card"] = base + card["frontAssetId"]
        sections = []
        for section in song["sections"]:
            lines = [lyrics.line_text(l) for l in lyrics.lyric_lines(song, section)]
            if lines:
                sections.append({"section": section["label"], "lines": lines})
        page["lyrics"] = sections
        allowed = set(photo_ids)
        allowed.update(c["assetId"] for c in song["tracks"]["ambience"]["clips"])
        if song["tracks"]["vocal"].get("renderAssetId"):
            allowed.add(song["tracks"]["vocal"]["renderAssetId"])
        if card.get("frontAssetId"):
            allowed.add(card["frontAssetId"])
        public = {k: v for k, v in song.items() if k not in ("seed", "provenance")}
        public["assets"] = [a for a in song["assets"] if a["id"] in allowed]
        public_card = dict(card)
        if not show_photo:
            public_card.pop("photoAssetIds", None)
            public_card.pop("coverAssetId", None)
        if not card.get("showCity"):
            public_card.pop("city", None)
        if public_card:
            public["card"] = public_card
        return {"page": page, "song": public}

    @app.get("/api/share/{share_id}/page")
    def get_share_page(share_id: str) -> Dict[str, Any]:
        return page_for(share_id)

    @app.get("/api/share/{share_id}/assets/{asset_id}")
    def get_share_asset(share_id: str, asset_id: str) -> Response:
        public = page_for(share_id)["song"]
        if not any(a["id"] == asset_id for a in public["assets"]):
            raise not_found("asset")
        info = store.asset_info(asset_id)
        return FileResponse(store.asset_path(asset_id), media_type=info["mime"])

    @app.get("/s/{share_id}")
    def song_page(share_id: str) -> Response:
        index = settings.app_dist / "song.html"
        if not index.is_file():
            return PlainTextResponse("The song page has not been built on this device (app/dist/song.html is missing).", status_code=404)
        return FileResponse(index, media_type="text/html")

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

    @app.get("/{path:path}", include_in_schema=False)
    def app_files(path: str) -> Response:
        """The built app (FRETCASE_APP_DIST): the song page loads its scripts and styles from here."""
        if path.split("/")[0] in ("api", "ws", "s", "health"):
            raise not_found("route")
        root = settings.app_dist.resolve()
        target = (root / (path or "index.html")).resolve()
        if root in target.parents and target.is_file():
            return FileResponse(target)
        return PlainTextResponse("Not found", status_code=404)

    return app


def scale_photo(data: bytes, mime: str) -> tuple:
    """A photo larger than 4096 px on its long side is scaled down on upload; anything else is stored as received."""
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as img:
            if max(img.size) <= MAX_PHOTO_SIDE:
                return data, mime
            fmt = (img.format or "JPEG").upper()
            img = ImageOps.exif_transpose(img)
            img.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE))
            out = io.BytesIO()
            if fmt == "PNG":
                img.save(out, format="PNG")
                return out.getvalue(), "image/png"
            img.convert("RGB").save(out, format="JPEG", quality=90)
            return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 (not an image PIL can read: stored as received)
        return data, mime


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
