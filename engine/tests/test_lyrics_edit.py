"""setLyrics: the whole section, or line by line."""
import pytest

from fretcase_engine import editing
from fretcase_engine.common import CannotApply


def section(song, sid="s-verse"):
    return next(s for s in song["sections"] if s["id"] == sid)


def test_a_new_song_has_lines_ending_at_line_end(song_cache):
    song = song_cache()
    lines = editing.lyric_lines(editing.vocal_notes_in(song, section(song)))
    assert len(lines) >= 2 and all(n["lyric"] == "la" for line in lines for n in line)
    assert all(line[-1].get("lineEnd") for line in lines)


def test_line_by_line_fits_each_line(song_cache):
    song = song_cache()
    lines = editing.lyric_lines(editing.vocal_notes_in(song, section(song)))
    words = "the sea wind blows to the night and all the lights come on".split()
    text = "\n".join(" ".join(words[i % len(words)] for i in range(len(l))) for l in lines)
    out = editing.set_lyrics(song, "s-verse", text)
    got = [editing.join_syllables([n["lyric"] for n in l]) for l in editing.lyric_lines(editing.vocal_notes_in(out, section(out)))]
    assert got == text.split("\n")


def test_line_errors_list_every_line_that_does_not_fit(song_cache):
    song = song_cache()
    lines = editing.lyric_lines(editing.vocal_notes_in(song, section(song)))
    counts = [len(l) for l in lines]
    good = [" ".join(["sea"] * c) for c in counts]
    bad = list(good)
    bad[0] = " ".join(["sea"] * (counts[0] + 1))
    bad[-1] = " ".join(["sea"] * (counts[-1] - 1))
    with pytest.raises(CannotApply) as caught:
        editing.set_lyrics(song, "s-verse", "\n".join(bad))
    assert caught.value.detail["lines"] == [
        {"index": 0, "noteCount": counts[0], "syllableCount": counts[0] + 1},
        {"index": len(counts) - 1, "noteCount": counts[-1], "syllableCount": counts[-1] - 1},
    ]
    # a missing or an extra line is reported too
    if len(counts) >= 3:  # with fewer lines left the text has no line breaks and is checked as a whole
        with pytest.raises(CannotApply) as caught:
            editing.set_lyrics(song, "s-verse", "\n".join(good[:-1]))
        assert caught.value.detail["lines"] == [{"index": len(counts) - 1, "noteCount": counts[-1], "syllableCount": 0}]
    with pytest.raises(CannotApply) as caught:
        editing.set_lyrics(song, "s-verse", "\n".join(good + ["more"]))
    assert caught.value.detail["lines"] == [{"index": len(counts), "noteCount": 0, "syllableCount": 1}]


def test_whole_section_mode_ignores_punctuation_and_reports_totals(song_cache):
    song = song_cache()
    count = len(editing.vocal_notes_in(song, section(song)))
    out = editing.set_lyrics(song, "s-verse", ", ".join(["sea"] * count))
    assert {n["lyric"] for n in editing.vocal_notes_in(out, section(out))} == {"sea"}
    with pytest.raises(CannotApply) as caught:
        editing.set_lyrics(song, "s-verse", "short")
    assert caught.value.detail == {"noteCount": count, "syllableCount": 1}
