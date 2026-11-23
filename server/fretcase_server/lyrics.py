"""Lyrics through the text-model adapter, with the guarantee that every line has exactly the right number of syllables.

The model proposes; the server checks. A line is accepted only when it has as many sung syllables as the lyric line
has notes. The model gives each line as an array of syllables ("walk-", "ing"), so the count is never guessed. Lines that fail are asked for again with the exact counts, up to
three calls within 45 s; if any still fail the call ends with ``503 offline_unavailable`` and ``detail.reason``
``bad_answer``. Nothing here is used when no model is configured (``reason: not_configured``).
"""
from __future__ import annotations

import concurrent.futures
import json
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fretcase_engine import editing
from fretcase_server.adapters import Adapters, ModelError, Offline
from fretcase_server.errors import ApiError, offline_unavailable

LYRICS_TIMEOUT_S = 20.0      # one model call
LYRICS_DEADLINE_S = 45.0     # everything one request may spend, retries included
LYRICS_ATTEMPTS = 3
SYSTEM = (
    "You write English song lyrics for people who are not musicians, to be sung on a melody that already exists. "
    "Each syllable is sung on exactly one note, so every line must have EXACTLY the number of syllables you are given. "
    "Write each line as a JSON array of its syllables in order, as they would be sung, marking a syllable that "
    "continues the same word with a trailing hyphen: \"walking by the sea\" is [\"walk-\", \"ing\", \"by\", \"the\", \"sea\"]. "
    "No punctuation or digits. Use everyday words and concrete images from what the person saw, heard and wrote; "
    "avoid clichés and big abstract words. Keep lines natural to say aloud. Answer with JSON only."
)
TONES = {"plain": "plain and direct, like talking to a friend", "subtle": "subtle and understated, showing rather than saying", "playful": "light and playful"}
ROLES = {
    "Intro": "intro: usually instrumental; if it has words, a quiet first image",
    "Verse": "verse: set the scene with concrete details of the place and moment",
    "Chorus": "chorus: the emotional heart; the simplest, most memorable lines, easy to sing along",
    "Outro": "outro: come back softly, an ending image or a quiet echo of the chorus",
}
PLACEHOLDER = "la"


def lyric_lines(song: Dict[str, Any], section: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    return editing.lyric_lines(editing.vocal_notes_in(song, section))


def line_text(notes: Sequence[Dict[str, Any]]) -> str:
    return editing.join_syllables([n.get("lyric") or "" for n in notes])


def syllable_count(text: str) -> int:
    return sum(len(line) for line in editing.split_syllables(text))


def _is_placeholder(text: str) -> bool:
    return not text or set(text.lower().split()) <= {PLACEHOLDER}


def inspiration(song: Dict[str, Any]) -> str:
    """What the person captured, in words the model can use. Never includes coordinates."""
    seed = song.get("seed") or {}
    texts = [i["text"] for i in seed.get("inputs", []) if i.get("kind") == "text" and i.get("text")]
    photos = [r["text"] for r in seed.get("reasons", []) if "photo" in r.get("text", "").lower()]
    kinds = {i.get("kind") for i in seed.get("inputs", [])}
    parts = []
    if texts:
        parts.append("What the person wrote: " + " / ".join(texts))
    if photos:
        parts.append("About their photos: " + "; ".join(photos))
    if "ambience" in kinds:
        parts.append("They also recorded the sounds around them.")
    if seed.get("mood"):
        parts.append(f"Mood: {seed['mood']}")
    city = (song.get("card") or {}).get("city")
    if city and (song.get("card") or {}).get("showCity"):
        parts.append(f"Place: {city}")
    time_of_day = (song.get("candidate") or {}).get("timeOfDay")
    if time_of_day:
        parts.append(f"Time of day: {dict(day='daytime', dusk='dusk', night='night').get(time_of_day, time_of_day)}")
    if song.get("title"):
        parts.append(f"Song title: {song['title']}")
    return "\n".join(parts)


def _parse_json(text: str) -> Any:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def _unavailable(reason: str) -> ApiError:
    """503 offline_unavailable with error.detail.reason, so the app can tell a missing key from no network."""
    err = offline_unavailable("Writing lyrics")
    err.detail = {**(err.detail or {}), "reason": reason}
    return err


def _ask(adapters: Adapters, prompt: str, timeout: float) -> Any:
    """One model call bounded by ``timeout``. Raises ApiError 503 with a reason; an unreadable answer returns None."""
    from fretcase_server.adapters import _POOL

    future = _POOL.submit(adapters.text_model.complete, SYSTEM, prompt, timeout=timeout)
    try:
        text = future.result(timeout=timeout + 1.0)  # a hard bound on top of the socket timeout
    except Offline as exc:
        raise _unavailable("not_configured") from exc
    except ModelError as exc:
        raise _unavailable(exc.reason) from exc
    except (concurrent.futures.TimeoutError, TimeoutError) as exc:
        raise _unavailable("timeout") from exc
    except Exception as exc:  # noqa: BLE001
        raise _unavailable("unreachable") from exc
    try:
        return _parse_json(text)
    except ValueError:
        return None


def _line_from(value: Any) -> List[str]:
    """A line as the model gave it, as its sung syllables: an array of syllables is taken as given (each one cleaned,
    a hyphen kept where the word goes on), a string is split by the spelling rule."""
    if isinstance(value, dict):
        value = value.get("syllables", value.get("chars", value.get("text", "")))
    if isinstance(value, list):
        out = []
        for v in value:
            syl = re.sub(r"[^\w'’\-]", "", str(v)).strip("'’")
            if syl.strip("-"):
                out.append(syl.lstrip("-"))
        return out
    parts = editing.split_syllables(str(value or ""))
    return parts[0] if len(parts) == 1 else []


def _as_text(syllables: Sequence[str]) -> str:
    """Syllables written so that ``editing.split_syllables`` gives exactly them back: "walk-ing by the sea"."""
    out = ""
    for syl in syllables:
        if out and not out.endswith("-"):
            out += " "
        out += syl
    return out.rstrip("-")


def _style_text(themes: Sequence[str], tone: str, rhyme: bool) -> str:
    parts = [f"Tone: {TONES.get(tone, TONES['plain'])}."]
    if themes:
        parts.append(f"Themes to draw on: {', '.join(themes)}.")
    parts.append(
        "Within each section, make the line endings rhyme, preferably on an open vowel that is easy to hold."
        if rhyme else "Rhyme is not needed."
    )
    return " ".join(parts)


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def write_lyrics(
    adapters: Adapters,
    song: Dict[str, Any],
    sections: Optional[Sequence[str]] = None,
    keep: Optional[Dict[str, List[int]]] = None,
    themes: Sequence[str] = (),
    tone: str = "plain",
    rhyme: bool = True,
    timeout: float = LYRICS_TIMEOUT_S,
    deadline_s: float = LYRICS_DEADLINE_S,
) -> Dict[str, str]:
    """New lyric text per section id (lines joined with newlines), kept lines unchanged. Raises ApiError 503."""
    keep = keep or {}
    deadline = time.monotonic() + deadline_s
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
    todo = [(sid, i) for sid, p in plan.items() for i in p["write"]]
    if not todo:
        return {}
    results: Dict[Tuple[str, int], str] = {}
    feedback: List[str] = []
    for attempt in range(LYRICS_ATTEMPTS):
        pending = [(sid, i) for sid, i in todo if (sid, i) not in results]
        if not pending:
            break
        left = _remaining(deadline)
        if left < 3.0:
            break
        structure = []
        for sid, p in plan.items():
            role = ROLES.get(p["label"], "")
            rows = []
            for i, count in enumerate(p["counts"]):
                if (sid, i) in results:
                    rows.append({"id": f"{sid}:{i}", "fixed": results[(sid, i)]})
                elif (sid, i) in pending:
                    rows.append({"id": f"{sid}:{i}", "syllables": count})
                elif not _is_placeholder(p["current"][i]):
                    rows.append({"id": f"{sid}:{i}", "fixed": p["current"][i]})
                else:
                    rows.append({"id": f"{sid}:{i}", "syllables": count, "note": "not needed now"})
            structure.append({"section": p["label"], "role": role, "lines": rows})
        prompt = (
            f"{inspiration(song)}\n{_style_text(themes, tone, rhyme)}\n\n"
            "The song, section by section. Lines marked \"fixed\" stay as they are; write every line that gives a "
            "number of \"syllables\" (skip lines marked \"not needed now\").\n"
            f"{json.dumps(structure, ensure_ascii=False)}\n\n"
            + ("Your last answer had lines of the wrong length:\n" + "\n".join(feedback) + "\nCount the syllables again.\n\n" if feedback else "")
            + 'Answer as JSON: {"lines": [{"id": "s-verse:0", "syllables": ["walk-", "ing", "..."]}]}'
        )
        answer = _ask(adapters, prompt, min(timeout, left))
        given: Dict[str, Any] = {}
        items = answer.get("lines") if isinstance(answer, dict) else None
        if isinstance(items, list):
            given = {str(it.get("id")): it for it in items if isinstance(it, dict)}
        elif isinstance(items, dict):  # {"<section id>": {"<index>": text}} is accepted too
            given = {f"{sid}:{i}": v for sid, d in items.items() if isinstance(d, dict) for i, v in d.items()}
        feedback = []
        for sid, i in pending:
            syls = _line_from(given.get(f"{sid}:{i}"))
            want = plan[sid]["counts"][i]
            if syls and len(syls) == want:
                results[(sid, i)] = _as_text(syls)
            else:
                feedback.append(f"- {sid}:{i} needs {want} syllables, you wrote {len(syls)}: {json.dumps(syls) if syls else '(nothing)'}")
    if any(key not in results for key in todo):
        raise _unavailable("bad_answer")
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
    deadline_s: float = LYRICS_DEADLINE_S,
) -> List[Dict[str, str]]:
    """Three other wordings of one line, each with exactly that line's number of syllables."""
    deadline = time.monotonic() + deadline_s
    lines = lyric_lines(song, section)
    if line >= len(lines):
        raise ApiError(422, "cannot_apply", "That section has no such lyric line", detail={"section": section["id"], "line": line})
    count = len(lines[line])
    current = line_text(lines[line])
    neighbours = [line_text(l) for j, l in enumerate(lines) if j != line and not _is_placeholder(line_text(l))]
    found: List[Dict[str, str]] = []
    seen = {current}
    wrong: List[str] = []
    for attempt in range(LYRICS_ATTEMPTS):
        need = 3 - len(found)
        left = _remaining(deadline)
        if need <= 0 or left < 3.0:
            break
        now = "has only placeholder syllables so far" if _is_placeholder(current) else f"now reads: {current}"
        prompt = (
            f"{inspiration(song)}\n{_style_text(themes, tone, rhyme)}\n\n"
            f"Section: {section['label']} ({ROLES.get(section['label'], '')}). Other lines in it: {json.dumps(neighbours, ensure_ascii=False)}\n"
            f"This line {now}.\nGive {need + 1} other wordings of this line, each EXACTLY {count} syllables, "
            "each with a very short note (2 to 4 words) saying how it differs, e.g. more understated, more images.\n"
            + ("These had the wrong length: " + "; ".join(wrong) + f". Each must be {count} syllables.\n" if wrong else "")
            + 'Answer as JSON: {"alternatives": [{"syllables": ["walk-", "ing", "..."], "note": "..."}]}'
        )
        answer = _ask(adapters, prompt, min(timeout, left))
        wrong = []
        for item in (answer.get("alternatives") if isinstance(answer, dict) else None) or []:
            if not isinstance(item, dict):
                continue
            syls = _line_from(item)
            if len(syls) != count:
                if syls:
                    wrong.append(f"{json.dumps(syls)} ({len(syls)})")
                continue
            text = _as_text(syls)
            if text in seen:
                continue
            seen.add(text)
            found.append({"text": text, "note": str(item.get("note", ""))[:32]})
    if len(found) < 3:
        if found:
            return found  # fewer than three is still useful
        raise _unavailable("bad_answer")
    return found[:3]


# ------------------------------------------------------------------------------------------- themes (offline)

PHOTO_THEMES = [("warm", "warm light"), ("cool", "cool air"), ("bright", "daylight"), ("dark", "night")]
# Words that make good lyric themes. Longer phrases first, so "sea breeze" wins over "sea".
THEME_WORDS = sorted(set("""
sea seaside sea breeze waves beach harbour harbor boat ship bridge shore tide wind breeze rain snow fog mist cloud clouds sky
stars starry sky moon sun sunset sunrise sunlight mountain mountains river lake trees tree flowers grass
morning afternoon evening dusk night midnight spring summer autumn winter lights street lights street streets alley
city road far away train plane station travel journey window home homesick going home hometown friends friend mum mom
dad child love missing you goodbye meeting waiting dream dreams time freedom lonely warm quiet coffee cat dog
""".strip().replace("street lights", "street-lights").replace("starry sky", "starry-sky").replace("sea breeze", "sea-breeze")
    .replace("far away", "far-away").replace("going home", "going-home").replace("missing you", "missing-you").split()), key=len, reverse=True)
THEME_WORDS = [w.replace("-", " ") for w in THEME_WORDS]
_CLAUSE = re.compile(r"[，。！？；、,.!?;:：\n]+")


def themes(song: Dict[str, Any]) -> List[Dict[str, str]]:
    """Suggested themes from what was captured, no model needed."""
    from fretcase_server.seed_analysis import KEYWORDS

    seed = song.get("seed") or {}
    inputs = seed.get("inputs", [])
    out: List[Dict[str, str]] = []

    def add(text: str, source: str) -> None:
        # Skip a theme that repeats one already listed ("sea" after "seaside", "home" after "going home").
        if text and not any(text in t["text"] or t["text"] in text for t in out):
            out.append({"text": text, "source": source})

    for item in inputs:
        if item.get("kind") != "text":
            continue
        text = item.get("text", "")
        low = " " + re.sub(r"[^a-z' ]+", " ", text.lower()) + " "
        rest = low
        for w in THEME_WORDS:
            if f" {w} " in rest:
                add(w, "text")
                rest = rest.replace(f" {w} ", " ")
        for words, _, _, _ in KEYWORDS:
            for w in words:
                if f" {w} " in low:
                    add(w, "text")
        # A short clause on its own (one to three words) is a theme as written; longer ones are never cut.
        for clause in _CLAUSE.split(text):
            words = clause.strip().split()
            if 1 <= len(words) <= 3 and all(re.match(r"^[A-Za-z'’]+$", w) for w in words):
                add(" ".join(words).lower(), "text")
    reasons = " ".join(r.get("text", "") for r in seed.get("reasons", []) if "photo" in r.get("text", "").lower())
    if any(i.get("kind") == "photo" for i in inputs):
        for marker, label in PHOTO_THEMES:
            if marker in reasons.lower():
                add(label, "photo")
    if any(i.get("kind") == "sound" for i in inputs):
        add("the sounds around", "sound")
    if seed.get("motif"):
        add("the tune I hummed", "hum")
    return out[:8]


def initial_texts(adapters: Adapters, song: Dict[str, Any]) -> Dict[str, str]:
    """Lyrics for a new song when a model is configured and answers in time; otherwise nothing ("la" stays)."""
    model = adapters.text_model
    if not getattr(model, "configured", True) or not hasattr(model, "complete"):
        return {}
    try:
        return write_lyrics(adapters, song, themes=[t["text"] for t in themes(song)][:4])
    except ApiError:
        return {}
