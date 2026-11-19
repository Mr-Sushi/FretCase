"""Runtime access to expert-calibrated weights and the expert benchmark gold.

Resolution order (first hit wins):
  1. server/data/hre_calibration.json          tracked, produced by scripts/calibrate_hre.py
  2. server/benchmark_outputs/calibration/summary.json   legacy, produced by expert_eval.py (gitignored)
  3. code defaults inside harmony_reasoning / arrangement_solver

The expert gold used by the phrase priors is read from server/data/expert_benchmark/ (tracked),
falling back to the legacy benchmark_outputs/aggregation/ location.
"""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVER_DIR / "data"
BENCHMARK_ROOT = SERVER_DIR / "benchmark_outputs"
# HRE weight keys; "wv" (chord-vocabulary fit) was added in feature version 2 and defaults to 0.0
HRE_WEIGHT_KEYS = ["wm", "wf", "wp", "wl", "wn", "wa", "wv"]
TRACKED_CALIBRATION_PATH = DATA_DIR / "hre_calibration.json"
LEGACY_CALIBRATION_PATH = BENCHMARK_ROOT / "calibration" / "summary.json"
GOLD_DIRS = (DATA_DIR / "expert_benchmark", BENCHMARK_ROOT / "aggregation")
PROMPT_VERSION = os.getenv("FRETSTUDIO_PROMPT_VERSION", "2026-03-27-planner-json-v2")


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_weight_dict(payload: Any, allowed_keys: List[str]) -> Dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    cleaned: Dict[str, float] = {}
    for key in allowed_keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            cleaned[key] = float(value)
        except (TypeError, ValueError):
            continue
    return cleaned


def _as_rows(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [dict(row) for row in payload if isinstance(row, dict)]


def _first_existing(name: str) -> Optional[Path]:
    for directory in GOLD_DIRS:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _file_fingerprint(path: Optional[Path]) -> str:
    if path is None or not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def weights_fingerprint(weights: Dict[str, float]) -> str:
    canonical = json.dumps({k: round(float(v), 6) for k, v in sorted(weights.items())}, sort_keys=True)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


@lru_cache(maxsize=1)
def load_runtime_expert_signals() -> Dict[str, Any]:
    tracked = _load_json(TRACKED_CALIBRATION_PATH)
    legacy = _load_json(LEGACY_CALIBRATION_PATH)
    source = "code_defaults"
    hre_weights: Dict[str, float] = {}
    calibration_version = "none"
    if isinstance(tracked, dict) and tracked.get("weights"):
        hre_weights = _as_weight_dict(tracked.get("weights"), HRE_WEIGHT_KEYS)
        calibration_version = str(tracked.get("version") or "tracked")
        source = "tracked_hre_calibration"
    elif isinstance(legacy, dict) and isinstance(legacy.get("hre"), dict):
        hre_weights = _as_weight_dict(legacy["hre"].get("best_weights"), HRE_WEIGHT_KEYS)
        calibration_version = "legacy_grid_summary"
        source = "legacy_benchmark_summary"

    acs_section = legacy.get("acs") if isinstance(legacy, dict) else {}
    final_section = legacy.get("final_scorer") if isinstance(legacy, dict) else {}
    if isinstance(tracked, dict):
        acs_section = tracked.get("acs") or acs_section
        final_section = tracked.get("final_scorer") or final_section

    canonical_path = _first_existing("canonical_gold.json")
    ranking_path = _first_existing("ranking_gold.json")
    canonical_gold = _as_rows(_load_json(canonical_path)) if canonical_path else []
    ranking_gold = _as_rows(_load_json(ranking_path)) if ranking_path else []

    return {
        "hre_weights": hre_weights,
        "acs_unary_weights": _as_weight_dict(
            acs_section.get("best_unary_weights") if isinstance(acs_section, dict) else {},
            ["um", "up", "ud", "ur"],
        ),
        "acs_pairwise_weights": _as_weight_dict(
            acs_section.get("best_pairwise_weights") if isinstance(acs_section, dict) else {},
            ["ts", "tf", "tc"],
        ),
        "final_weights": _as_weight_dict(
            final_section.get("best_weights") if isinstance(final_section, dict) else {},
            ["alpha", "beta", "gamma"],
        ),
        "canonical_gold": canonical_gold,
        "ranking_gold": ranking_gold,
        "calibration_source": source,
        "calibration_version": calibration_version,
        "calibration_path": str(TRACKED_CALIBRATION_PATH if source == "tracked_hre_calibration" else LEGACY_CALIBRATION_PATH),
        "canonical_gold_path": str(canonical_path) if canonical_path else None,
        "canonical_gold_fingerprint": _file_fingerprint(canonical_path),
    }


def _default_harmony_source() -> str:
    """The candidate source the server will actually use by default (falls back to the library when no key)."""
    try:
        from fretcase_engine.candidate_sources import resolve_harmony_source
    except ImportError:  # pragma: no cover - script-mode import
        from candidate_sources import resolve_harmony_source  # type: ignore
    api_key_present = bool(os.getenv("GPT_API_KEY") or os.getenv("OPENAI_API_KEY"))
    forced_offline = os.getenv("FRETSTUDIO_OFFLINE", "").strip().lower() in {"1", "true", "yes"}
    return resolve_harmony_source(None, api_key_present=api_key_present and not forced_offline)


def runtime_provenance() -> Dict[str, Any]:
    """Compact provenance record attached to generation results and /health."""
    signals = load_runtime_expert_signals()
    try:
        from fretcase_engine.arrangement_solver import voicing_library_fingerprint, voicing_library_stats
    except ImportError:  # pragma: no cover - script-mode import
        from arrangement_solver import voicing_library_fingerprint, voicing_library_stats  # type: ignore
    try:
        from fretcase_engine.harmony_reasoning import score_hre_breakdown
    except ImportError:  # pragma: no cover
        from harmony_reasoning import score_hre_breakdown  # type: ignore
    defaults = score_hre_breakdown.__kwdefaults__ or {}
    if not defaults:
        import inspect

        defaults = {
            name: param.default
            for name, param in inspect.signature(score_hre_breakdown).parameters.items()
            if name in set(HRE_WEIGHT_KEYS)
        }
    effective = dict(defaults)
    effective.update(signals.get("hre_weights") or {})
    stats = voicing_library_stats()
    return {
        "model": os.getenv("FRETSTUDIO_OPENAI_MODEL", "gpt-4o"),
        "harmony_source": _default_harmony_source(),
        "prompt_version": PROMPT_VERSION,
        "hre_weights": {k: round(float(v), 4) for k, v in effective.items()},
        "hre_weights_hash": weights_fingerprint(effective),
        "hre_calibration": signals.get("calibration_version"),
        "hre_calibration_source": signals.get("calibration_source"),
        "expert_phrase_priors": os.getenv("FRETSTUDIO_EXPERT_PHRASE_PRIORS", "on"),
        "canonical_gold_fingerprint": signals.get("canonical_gold_fingerprint"),
        "voicing_library": {
            "fingerprint": voicing_library_fingerprint(),
            "symbols": stats.get("symbols"),
            "voicings": stats.get("voicings"),
            "source": stats.get("source"),
        },
    }
