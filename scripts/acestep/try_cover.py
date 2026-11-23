#!/usr/bin/env python3
"""FretCase: try ACE-Step 1.5 "cover" mode on our own arrangement.

Sends arrangement.mp3 (the demo song as the app plays it, with the guide voice humming the tune) and lyrics.txt
to the ACE-Step API server on this Mac, three times with a different audio_cover_strength, and saves what comes
back in results/. A high strength should keep our melody, chords and structure; a lower one gives the model more
freedom. Uses only the Python standard library.

    python3 try_cover.py                      # strengths 1.0, 0.7 and 0.45
    python3 try_cover.py 0.85                 # one strength
    ACESTEP_URL=http://127.0.0.1:8001 python3 try_cover.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = os.environ.get("ACESTEP_URL", "http://127.0.0.1:8001").rstrip("/")
KEY = os.environ.get("ACESTEP_API_KEY", "")
SOURCE = HERE / "arrangement.mp3"
LYRICS = (HERE / "lyrics.txt").read_text(encoding="utf-8").strip()
CAPTION = ("acoustic folk song, warm male lead vocal, clear English lyrics, strummed steel-string guitar, "
           "harmonica, finger bass, soft brushed drums, intimate, sea waves in the background")
SONG = {"bpm": "84", "key_scale": "D major", "time_signature": "4", "vocal_language": "en"}
OUT = HERE / "results"


def call(method, path, body=None, headers=None, timeout=60):
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    if KEY:
        req.add_header("Authorization", f"Bearer {KEY}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def multipart(fields, files):
    boundary = "----fretcase" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    for name, path in files.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{path.name}"\r\nContent-Type: audio/mpeg\r\n\r\n'
        parts.append(head.encode("utf-8") + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def wait_for_server(minutes=30):
    print(f"Waiting for the ACE-Step server at {BASE} ...", flush=True)
    end = time.time() + minutes * 60
    while time.time() < end:
        try:
            call("GET", "/health", timeout=5)
            print("The server is up.\n", flush=True)
            return
        except (urllib.error.URLError, OSError):
            time.sleep(3)
    sys.exit("No answer. Is 1-install-and-start.command still running in another window?")


def cover(strength):
    fields = {
        "task_type": "cover", "prompt": CAPTION, "lyrics": LYRICS, "audio_cover_strength": str(strength),
        "batch_size": "1", "audio_format": "mp3", "thinking": "false", **SONG,
    }
    body, headers = multipart(fields, {"src_audio": SOURCE})
    answer = json.loads(call("POST", "/release_task", body, headers, timeout=120))
    task = (answer.get("data") or {}).get("task_id")
    if not task:
        print("  The server did not accept the request:", json.dumps(answer)[:600])
        return None
    print(f"  strength {strength}: task {task}", flush=True)
    started = time.time()
    while time.time() - started < 60 * 60:
        time.sleep(4)
        raw = call("POST", "/query_result", json.dumps({"task_id_list": [task]}).encode(), {"Content-Type": "application/json"})
        items = json.loads(raw).get("data") or []
        item = items[0] if items else {}
        status = item.get("status")
        if status == 1:
            result = item.get("result")
            entries = json.loads(result) if isinstance(result, str) else (result or [])
            saved = []
            for i, entry in enumerate(entries):
                url = entry.get("file") or ""
                if not url:
                    continue
                audio = call("GET", url if url.startswith("/") else "/" + url, timeout=300)
                name = OUT / f"cover-strength-{strength}{'' if i == 0 else f'-{i + 1}'}.mp3"
                name.write_bytes(audio)
                saved.append(name)
            took = round(time.time() - started)
            print(f"  strength {strength}: done in {took} s -> {', '.join(p.name for p in saved) or 'no audio in the answer'}", flush=True)
            (OUT / f"cover-strength-{strength}.json").write_text(json.dumps({"seconds": took, "entries": entries}, indent=1), encoding="utf-8")
            return saved
        if status == 2:
            print(f"  strength {strength}: the server reports a failure:", str(item.get("result"))[:800])
            (OUT / f"cover-strength-{strength}.error.txt").write_text(json.dumps(item, indent=1), encoding="utf-8")
            return None
        print(f"    ... still working ({round(time.time() - started)} s)", flush=True)
    print(f"  strength {strength}: gave up after 60 minutes")
    return None


def main():
    strengths = [float(a) for a in sys.argv[1:]] or [1.0, 0.7, 0.45]
    OUT.mkdir(exist_ok=True)
    wait_for_server()
    print("Asking for the demo song, sung over our arrangement (the first one also loads the model):")
    made = [s for s in strengths if cover(s)]
    print()
    if made:
        print(f"Done. Listen to the files in {OUT}")
        print("For each one: are the words sung clearly, and is it still our tune?")
        print("Then tell Claude it is finished; it can read the results folder and compare them with the arrangement.")
    else:
        print("Nothing came back. Copy what the server window printed and send it to Claude.")
    if sys.stdin.isatty():
        input("\nPress Enter to close. ")


if __name__ == "__main__":
    main()
