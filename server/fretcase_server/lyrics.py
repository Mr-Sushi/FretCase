"""Lyrics through the text-model adapter, with the guarantee that every line has exactly the right number of syllables.

The model proposes; the server checks. A line is accepted only when it has as many syllables (Chinese characters,
punctuation ignored) as the lyric line has notes. Lines that fail are asked for once more; if they still fail the call
ends with ``503 offline_unavailable``. Nothing here is used when no model is configured.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fretcase_engine import editing
from fretcase_server.adapters import Adapters, Offline
from fretcase_server.errors import ApiError, offline_unavailable

LYRICS_TIMEOUT_S = 20.0
SYSTEM = (
    "You write short, singable Chinese song lyrics. Use plain, concrete words from everyday life. "
    "Every line must have EXACTLY the number of Chinese characters you are told (punctuation is not counted and "
    "should not be used). Answer with JSON only, no explanation."
)
TONES = {"plain": "plain and direct", "subtle": "subtle and understated", "playful": "light and playful"}


def lyric_lines(song: Dict[str, Any], section: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    return editing.lyric_lines(editing.vocal_notes_in(song, section))


def line_text(notes: Sequence[Dict[str, Any]]) -> str:
    return "".join(n.get("lyric") or "" for n in notes)


def syllable_count(text: str) -> int:
    return sum(len(line) for line in editing.split_syllables(text))


def inspiration(song: Dict[str, Any]) -> str:
    seed = song.get("seed") or {}
    texts = [i["text"] for i in seed.get("inputs", []) if i.get("kind") == "text" and i.get("text")]
    photos = [r["text"] for r in seed.get("reasons", []) if "照片" in r.get("text", "")]
    mood = seed.get("mood") or ""
    return "；".join(filter(None, [f"words from the user: {' / '.join(texts)}" if texts else "", f"photo colours: {'; '.join(photos)}" if photos else "", f"mood: {mood}" if mood else ""]))


def _parse_json(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def _ask(adapters: Adapters, prompt: str, timeout: float) -> Any:
    """One model call. Offline -> 503; any failure (timeout, HTTP error, unreadable answer) -> 503."""
    try:
        text = adapters.text_model.complete(SYSTEM, prompt, timeout=timeout)
        return _parse_json(text)
    except Offline as exc:
        raise offline_unavailable("Writing lyrics") from exc
    except Exception as exc:  # noqa: BLE001 (timeout, HTTP error, bad JSON: the server answers 503)
        raise offline_unavailable("Writing lyrics") from exc


def _style_text(themes: Sequence[str], tone: str, rhyme: bool) -> str:
    parts = [f"Tone: {TONES.get(tone, TONES['plain'])}."]
    if themes:
        parts.append(f"Themes to draw on: {', '.join(themes)}.")
    parts.append("Rhyme the last syllable of lines that end together." if rhyme else "Rhyme is not needed.")
    return " ".join(parts)


def write_lyrics(
    adapters: Adapters,
    song: Dict[str, Any],
    sections: Optional[Sequence[str]] = None,
    keep: Optional[Dict[str, List[int]]] = None,
    themes: Sequence[str] = (),
    tone: str = "plain",
    rhyme: bool = True,
    timeout: float = LYRICS_TIMEOUT_S,
) -> Dict[str, str]:
    """New lyric text per section id (lines joined with newlines), kept lines unchanged. Raises ApiError 503."""
    keep = keep or {}
    wanted = [s for s in song["sections"] if (sections is None or s["id"] in sections)]
    plan: Dict[str, Dict[str, Any]] = {}
    for section in wanted:
        lines = lyric_lines(song, section)
        if not lines:
            continue
        kept = set(keep.get(section["id"], []))
        plan[section["id"]] = {
            "label": section["label"],
            "counts": [len(l) for l in lines],
            "current": [line_text(l) for l in lines],
            "write": [i for i in range(len(lines)) if i not in kept],
        }
    todo = {sid: p["write"] for sid, p in plan.items() if p["write"]}
    if not todo:
        return {}
    results: Dict[Tuple[str, int], str] = {}
    for attempt in range(2):
        pending = {sid: [i for i in idx if (sid, i) not in results] for sid, idx in todo.items()}
        pending = {sid: idx for sid, idx in pending.items() if idx}
        if not pending:
            break
        spec = {
            sid: [{"line": i, "syllables": plan[sid]["counts"][i], "now": plan[sid]["current"][i]} for i in idx]
            for sid, idx in pending.items()
        }
        context = {sid: [t for j, t in enumerate(plan[sid]["current"]) if j not in todo.get(sid, [])] for sid in pending}
        prompt = (
            f"{inspiration(song)}\n{_style_text(themes, tone, rhyme)}\n"
            f"Write new lyrics for these lines. Each entry gives the line index and the exact number of syllables.\n"
            f"Lines: {json.dumps(spec, ensure_ascii=False)}\n"
            f"Lines that stay as they are (for context): {json.dumps(context, ensure_ascii=False)}\n"
            + ("Your earlier answer had lines of the wrong length; count again.\n" if attempt else "")
            + 'Answer as JSON: {"lines": {"<section id>": {"<line index>": "<text>"}}}'
        )
        answer = _ask(adapters, prompt, timeout)
        given = answer.get("lines") if isinstance(answer, dict) else None
        if not isinstance(given, dict):
            continue
        for sid, idx in pending.items():
            for i in idx:
                text = str((given.get(sid) or {}).get(str(i), "")) if isinstance(given.get(sid), dict) else ""
                if text and syllable_count(text) == plan[sid]["counts"][i] and len(editing.split_syllables(text)) == 1:
                    results[(sid, i)] = "".join(editing.split_syllables(text)[0])
    if any((sid, i) not in results for sid, idx in todo.items() for i in idx):
        raise offline_unavailable("Writing lyrics")
    out = {}
    for sid, p in plan.items():
        texts = [results.get((sid, i), p["current"][i]) for i in range(len(p["counts"]))]
        out[sid] = "\n".join(texts)
    return out


def alternatives(
    adapters: Adapters,
    song: Dict[str, Any],
    section: Dict[str, Any],
    line: int,
    themes: Sequence[str] = (),
    tone: str = "plain",
    rhyme: bool = True,
    timeout: float = LYRICS_TIMEOUT_S,
) -> List[Dict[str, str]]:
    """Three other wordings of one line, each with exactly that line's number of syllables."""
    lines = lyric_lines(song, section)
    if line >= len(lines):
        raise ApiError(422, "cannot_apply", "That section has no such lyric line", detail={"section": section["id"], "line": line})
    count = len(lines[line])
    current = line_text(lines[line])
    found: List[Dict[str, str]] = []
    seen = {current}
    for attempt in range(2):
        need = 3 - len(found)
        if need <= 0:
            break
        prompt = (
            f"{inspiration(song)}\n{_style_text(themes, tone, rhyme)}\n"
            f"The line now reads: {current}\nGive {need} other wordings of this line, each with EXACTLY {count} syllables, "
            f"each with a very short note (2 to 4 characters) saying how it differs, e.g. 更含蓄.\n"
            + ("Your earlier answer had lines of the wrong length; count again.\n" if attempt else "")
            + 'Answer as JSON: {"alternatives": [{"text": "...", "note": "..."}]}'
        )
        answer = _ask(adapters, prompt, timeout)
        for item in (answer.get("alternatives") if isinstance(answer, dict) else None) or []:
            if not isinstance(item, dict):
                continue
            parts = editing.split_syllables(str(item.get("text", "")))
            if len(parts) != 1 or len(parts[0]) != count:
                continue
            text = "".join(parts[0])
            if text in seen:
                continue
            seen.add(text)
            found.append({"text": text, "note": str(item.get("note", ""))[:12]})
    if len(found) < 3:
        raise offline_unavailable("Writing lyrics")
    return found[:3]


# ------------------------------------------------------------------------------------------- themes (offline)

PHOTO_THEMES = [("偏暖", "暖光"), ("偏冷", "清冷"), ("偏亮", "白天"), ("偏暗", "夜晚")]
_CJK_CHUNK = re.compile(r"[一-鿿]{1,4}")
_STOP = set("的了是在我你他她它们和与就都也很把被给让呢吗吧啊")


def themes(song: Dict[str, Any]) -> List[Dict[str, str]]:
    """Suggested themes from what was captured, no model needed."""
    from fretcase_server.seed_analysis import KEYWORDS

    seed = song.get("seed") or {}
    inputs = seed.get("inputs", [])
    out: List[Dict[str, str]] = []

    def add(text: str, source: str) -> None:
        if text and text not in {t["text"] for t in out}:
            out.append({"text": text, "source": source})

    for item in inputs:
        if item.get("kind") != "text":
            continue
        text = item.get("text", "")
        for words, _, _, _ in KEYWORDS:
            for w in words:
                if w in text and re.match(r"^[一-鿿]+$", w):
                    add(w, "text")
        for chunk in _CJK_CHUNK.findall(text):
            if len(chunk) >= 2 and not set(chunk) <= _STOP:
                add(chunk, "text")
    reasons = " ".join(r.get("text", "") for r in seed.get("reasons", []) if "照片" in r.get("text", ""))
    if any(i.get("kind") == "photo" for i in inputs):
        for marker, label in PHOTO_THEMES:
            if marker in reasons:
                add(label, "photo")
    if any(i.get("kind") == "sound" for i in inputs):
        add("身边的声音", "sound")
    if seed.get("motif"):
        add("哼过的旋律", "hum")
    return out[:8]


def initial_texts(adapters: Adapters, song: Dict[str, Any]) -> Dict[str, str]:
    """Lyrics for a new song when a model is configured and answers in time; otherwise nothing (啦 stays)."""
    model = adapters.text_model
    if not getattr(model, "configured", True) or not hasattr(model, "complete"):
        return {}
    try:
        return write_lyrics(adapters, song, themes=[t["text"] for t in themes(song)][:4])
    except ApiError:
        return {}
