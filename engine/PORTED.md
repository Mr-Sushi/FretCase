# Code ported from FretStudio

Source: the FretStudio working tree at `/home/claude/work/fretstudio-src/server/` (newer than FretStudio `main`, as `docs/porting-from-fretstudio.md` asks).
Only import statements were changed: `server.X` became `fretcase_engine.X`, and the bare `constraint_engine` imports became package imports. The `except ImportError` script-mode fallbacks that FretStudio has are left as they were.

## On the porting list

`harmony_reasoning`, `arrangement_solver`, `capo`, `chord_spelling`, `chord_changes`, `voicing_check`, `constraint_engine`, `candidate_sources`, `candidate_summary`, `offline_melody`.

Data (in `fretcase_engine/data/`): `guitar_voicings.json`, `hre_calibration.json`, `hre_priors.json`, `progression_library.json`, `acs_type_difficulty.json`, `acs_transition_priors.json`, `beginner_shapes.json`, and `sources/` (chords-db 0.5.1 guitar data and its MIT licence, kept for attribution).

## Copied beyond the list (imported by listed modules)

| Module / file | Why |
| --- | --- |
| `learner_model.py` | `normalize_chord_symbol` is used by `harmony_reasoning`, `arrangement_solver`, `candidate_sources`, `candidate_summary`, `chord_changes` |
| `music_representation.py` | `LeadSheetGraph`, `NoteEvent`, `parse_abc_to_graph` used by `harmony_reasoning`, `candidate_sources`, `capo`, `constraint_engine` |
| `expert_runtime.py` | `harmony_reasoning` loads calibrated weights through it |
| `playability_critic.py` | imported by `learner_model` |
| `key_tempo_validator.py` | imported by `constraint_engine` |
| `data/choco_freq.json` | read by `harmony_reasoning` (`CHOCO_FREQ_PATH`) |
| `data/expert_benchmark/` | read by `expert_runtime` for the phrase priors (`canonical_gold.json`, `ranking_gold.json` and pairwise csv) |

## Not ported

`harmony_reranker.py`, `expert_eval.py`, `recourse_engine.py`, `engine.py`, `main.py`, `learner_store.py`, `study_log.py`, `routers/` (listed under "do not port", or part of FretStudio's app). The FretCase pipeline that replaces the reranker is new code in `fretcase_engine/harmonise.py`.

## Tests

Ported test files are in `tests/ported/`, with the same import-only changes (plus the `patch("constraint_engine.check_key_compliance")` target strings, which are module paths). Test functions that need a module that is not ported were removed, not edited:

| File | Removed test functions | Needs |
| --- | --- | --- |
| `test_capo.py` | `_rows` helper; `test_leading_tone_heavy_minor_melody_keeps_its_basic_lane`, `test_bb_major_basic_lane_is_arranged_with_capo_three_and_sounds_in_bb`, `test_capo_version_wins_when_it_is_clearly_easier_to_fret`, `test_capo_never_keeps_the_plain_arrangement`, `test_open_keys_never_use_a_capo`, `test_barre_start_keys_get_three_checked_options` (parametrised), `test_capo_flow_through_the_api`, `test_start_screen_flow_in_eb_major` | `harmony_reranker`, `main`, `learner_store`, `study_log` |
| `test_chord_spelling.py` | `_basic_lane` helper; `test_minor_keys_get_a_basic_lane_with_a_real_dominant`, `test_e_major_basic_lane_uses_b7_when_b_needs_a_barre` | `harmony_reranker` |
| `test_harmony_symbolic_pipeline.py` | `test_symbolic_harmony_pipeline_builds_verified_candidates`, `test_traditional_basic_pipeline_keeps_major_key_triads_only` | `harmony_reranker` |
| `test_hre_v2.py` | `test_ranking_option_style_follows_the_item_lane_not_the_chord_symbols` | `expert_eval` |
| `test_offline_pipeline.py` | `test_symbolic_pipeline_runs_on_library_hypotheses_for_all_three_lanes`, `test_offline_engine_generates_melody_harmony_rhythm_and_explanation`, `test_study_log_is_append_only_and_migrates_legacy_files`, `test_api_offline_round_trip` | `harmony_reranker`, `engine`, `study_log`, `main` |
| `test_abc_key_signature.py` | `test_replacing_a_slot_respells_the_rest_of_the_bar` | `recourse_engine` |

Not copied at all (they test code that is not ported): `test_expert_eval`, `test_export_audio`, `test_harmony_abc`, `test_harmony_explanation_grounding`, `test_harmony_runtime`, `test_intent_recourse`, `test_learner_recourse`, `test_learning_features`, `test_melody_assessment`, `test_midi_seed_conditioning`, `test_practice_sheet_pdf`, `test_rhythm_validator`, `test_simple_melody`.

Run: `uv run pytest engine/tests/ported`
