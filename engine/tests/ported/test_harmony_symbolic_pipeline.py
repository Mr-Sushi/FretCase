import os
import sys

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SERVER_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fretcase_engine.arrangement_solver import (
    build_acs_learner,
    build_default_constraint_spec,
    build_default_voicing_inventory,
    decode_voicings_viterbi,
    feasible_voicings_for_step,
    type_difficulty_prior,
    voicing_candidates_for_symbol,
)
from fretcase_engine.harmony_reasoning import (
    LearnerProfile,
    LessonSpec,
    HREContext,
    MelodyEvent,
    apply_llm_hints,
    beam_search_chord_sequences,
    build_candidate_bank,
    build_hre_contexts,
    derive_candidate_from_symbol,
    evaluate_candidate,
    key_scale_pcs,
    score_hre_breakdown,
)
from fretcase_engine.music_representation import parse_abc_to_graph


MELODY_ABC = """X:1
T:Mini Phrase
M:4/4
L:1/8
Q:1/4=84
K:C
V:1
E2 G2 C2 E2 | F2 A2 D2 F2 | G2 B2 d2 G2 | C4 E2 G2 |
"""


def test_detect_chord_symbol_supports_major_and_minor_sevenths() -> None:
    abc = """X:1
T:Seventh Parse
M:4/4
L:1/8
K:C
%%staves [1 2]
V:1
C8 |
V:2
[C E G B]8 | [D F A C]8 |
"""
    graph = parse_abc_to_graph(abc)
    assert graph.harmony[0].symbol == "Cmaj7"
    assert graph.harmony[1].symbol == "Dm7"


def test_hre_prefers_predominant_in_pre_cadential_context() -> None:
    ctx = HREContext(
        key_scale_pcs=key_scale_pcs("C", "major"),
        phrase_role="pre_cadential",
        lesson=LessonSpec(target_complexity=0.25, target_functions={"PD"}),
        learner=LearnerProfile(harmonic_cap=0.4),
        history_symbols=["C"],
    )
    prev = derive_candidate_from_symbol("C", tonic="C", mode="major")
    ii = derive_candidate_from_symbol("Dm", tonic="C", mode="major")
    tonic = derive_candidate_from_symbol("C", tonic="C", mode="major")
    events = [MelodyEvent(pitch_class=5, beat_strength=1.0, duration_norm=1.0)]

    ii_eval = evaluate_candidate(events, ii, prev, ctx, tonic="C", mode="major")
    tonic_eval = evaluate_candidate(events, tonic, prev, ctx, tonic="C", mode="major")
    assert ii_eval.total > tonic_eval.total
    assert ii_eval.function == "PD"


def test_arrangement_solver_decodes_open_voicing_path() -> None:
    inventory = build_default_voicing_inventory()
    spec = build_default_constraint_spec(render_mode="playable", style="pop", allow_barre=False)
    learner = build_acs_learner(skill_level="beginner", render_mode="playable")

    candidates_by_t = [
        feasible_voicings_for_step("C", 0, spec, learner, inventory=inventory),
        feasible_voicings_for_step("Dm", 5, spec, learner, inventory=inventory),
        feasible_voicings_for_step("G7", 7, spec, learner, inventory=inventory),
    ]
    score, path = decode_voicings_viterbi(candidates_by_t, [0, 5, 7], spec, learner)
    assert score > 0
    assert len(path) == 3


def test_minor_symbol_does_not_expand_to_major_voicings() -> None:
    candidates = voicing_candidates_for_symbol("Am")
    assert candidates
    assert all(1 not in voicing.pitch_classes for voicing in candidates)


def test_lane_conditioned_acs_is_stricter_for_basic_than_color() -> None:
    basic_spec = build_default_constraint_spec(
        render_mode="playable",
        style="pop",
        allow_barre=True,
        lane="basic",
    )
    color_spec = build_default_constraint_spec(
        render_mode="playable",
        style="pop",
        allow_barre=True,
        lane="color",
    )
    basic_learner = build_acs_learner(
        skill_level="early_intermediate",
        render_mode="playable",
        lane="basic",
    )
    color_learner = build_acs_learner(
        skill_level="early_intermediate",
        render_mode="playable",
        lane="color",
    )

    assert not basic_spec.allow_barre
    assert color_spec.allow_barre
    assert basic_spec.max_shift < color_spec.max_shift
    assert basic_spec.max_pitch_move < color_spec.max_pitch_move
    assert basic_learner.max_difficulty < color_learner.max_difficulty


def test_basic_mode_simplifies_planner_seventh_hints_to_core_triads() -> None:
    base = build_candidate_bank(tonic="C", mode="major", style="traditional", render_mode="playable")
    pool = apply_llm_hints(
        base_candidates=base,
        planner_symbols=["Am7", "Fmaj7", "G7"],
        tonic="C",
        mode="major",
        basic_only=True,
    )
    symbols = {candidate.symbol for candidate in pool}
    assert "Am" in symbols
    assert "F" in symbols
    assert "G" in symbols
    assert "Am7" not in symbols
    assert "Fmaj7" not in symbols


def test_hre_penalizes_immediate_chord_repetition() -> None:
    ctx = HREContext(
        key_scale_pcs=key_scale_pcs("C", "major"),
        phrase_role="middle",
        lesson=LessonSpec(target_complexity=0.25, target_functions={"T", "PD"}),
        learner=LearnerProfile(harmonic_cap=0.4),
        history_symbols=["Am"],
    )
    prev = derive_candidate_from_symbol("Am", tonic="C", mode="major")
    repeated = derive_candidate_from_symbol("Am", tonic="C", mode="major")
    varied = derive_candidate_from_symbol("F", tonic="C", mode="major")
    events = [MelodyEvent(pitch_class=9, beat_strength=1.0, duration_norm=1.0)]

    repeated_score = score_hre_breakdown(events, repeated, prev, ctx)["total"]
    varied_score = score_hre_breakdown(events, varied, prev, ctx)["total"]
    assert varied_score > repeated_score


def test_beam_search_prefers_non_repeating_chord_when_alternative_exists() -> None:
    events_by_t = [
        [MelodyEvent(pitch_class=4, beat_strength=1.0, duration_norm=1.0)],
        [MelodyEvent(pitch_class=4, beat_strength=1.0, duration_norm=1.0)],
    ]
    candidate_pools = [
        [derive_candidate_from_symbol("C", tonic="C", mode="major")],
        [
            derive_candidate_from_symbol("C", tonic="C", mode="major"),
            derive_candidate_from_symbol("Am", tonic="C", mode="major"),
        ],
    ]
    contexts = build_hre_contexts(
        bar_count=2,
        tonic="C",
        mode="major",
        style="traditional",
        function_hints=["T", "T"],
        phrase_roles=["start", "middle"],
        harmonic_cap=0.4,
        user_goal="keep the phrase singable",
    )

    beam = beam_search_chord_sequences(
        events_by_t=events_by_t,
        candidate_pools_by_t=candidate_pools,
        contexts_by_t=contexts,
        tonic="C",
        mode="major",
        beam_width=4,
        per_step_limit=4,
    )

    assert beam
    best_path = beam[0][1]
    assert len(best_path) == 2
    assert best_path[0].chord.symbol == "C"
    assert best_path[1].chord.symbol == "Am"


def test_acs_type_prior_falls_back_to_builtin_defaults_when_json_is_empty() -> None:
    assert type_difficulty_prior("C", "m7") < 0.5
    assert type_difficulty_prior("B", "dim") > type_difficulty_prior("C", "")




