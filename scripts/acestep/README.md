# FretCase × ACE-Step 1.5: a first try on this Mac

Goal: find out whether ACE-Step's "cover" mode can sing our lyrics while keeping our own tune and chords.

1. Double-click `1-install-and-start.command`. It clones ACE-Step 1.5 into `~/ACE-Step-1.5`, installs its Python
   environment with `uv` and starts the API server on http://127.0.0.1:8001. About 20 GB of disk and a good
   connection are needed; the first start downloads the models. Leave the window open.
   If macOS refuses to open it, run `bash 1-install-and-start.command` in Terminal from this folder.
2. When that window says the server is running, double-click `2-try-cover.command`. It sends `arrangement.mp3`
   (the demo song as the app plays it, guide voice included) and `lyrics.txt` three times, with
   `audio_cover_strength` 1.0, 0.7 and 0.45, and saves the songs in `results/`.
3. Listen: are the words clear, and is it still our tune? Then tell Claude the results are there.

To stop the server, close its window. To remove everything: delete `~/ACE-Step-1.5` and this folder
(the models are inside `~/ACE-Step-1.5/checkpoints`).

Nothing here changes FretCase itself. If the result is good, the next step is an ACE-Step adapter in
`server/fretcase_server/adapters.py`, next to the Lyria one.

`arrangement.mp3` is not in the repository: save the demo song from the song page (or render it with the app) and put it next to these files.
