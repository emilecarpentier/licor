from __future__ import annotations

from pathlib import Path

from licor.analysis.experimental_live_validation_pack import (
    ExperimentalLiveValidationPackConfig,
    write_experimental_live_validation_pack,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENTAL_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "experimental" / "spa_dynamics_v1"
PACK_OUTPUT_DIR = EXPERIMENTAL_OUTPUT_DIR / "live_validation_packs"
PROTOCOL_DOC_PATH = PROJECT_ROOT / "docs" / "spa_adaptive_live_validation_protocol.md"
REPLAY_VALIDATION_REPORT_PATH = (
    EXPERIMENTAL_OUTPUT_DIR
    / "spa_lmp2_experimental_observed_adaptive_live_replay_validation_report.html"
)
REPLANNER_VALIDATION_REPORT_PATH = (
    EXPERIMENTAL_OUTPUT_DIR
    / "spa_lmp2_experimental_observed_replanner_validation_report.html"
)


def main() -> int:
    packs = [
        (
            EXPERIMENTAL_OUTPUT_DIR
            / "spa_lmp2_experimental_live_candidate_selected_zones_plan.csv",
            ExperimentalLiveValidationPackConfig(
                variant_key="selected_zones_v1",
                recommended_run_nickname="recommendation_execution_selected_01",
                planned_lico_profile_id="spa_exp_live_candidate_selected_v1",
                planned_lico_profile_description="First pilot live validation candidate from range_aware_selected_zones.",
                warmup_lap_count=2,
                scored_lap_count=3,
                include_t14=False,
                pack_status="archived_predecessor",
                status_summary=(
                    "Archived superseded selected-zones live validation predecessor."
                ),
            ),
        ),
        (
            EXPERIMENTAL_OUTPUT_DIR
            / "spa_lmp2_experimental_live_candidate_all_eligible_plan.csv",
            ExperimentalLiveValidationPackConfig(
                variant_key="all_eligible_v1",
                recommended_run_nickname="recommendation_execution_all_eligible_01",
                planned_lico_profile_id="spa_exp_live_candidate_all_eligible_v1",
                planned_lico_profile_description="First pilot live validation candidate from range_aware_all_eligible_zones.",
                warmup_lap_count=1,
                scored_lap_count=3,
                include_t14=True,
                pack_status="archived_predecessor",
                status_summary=(
                    "Archived superseded all-eligible live validation predecessor."
                ),
            ),
        ),
        (
            EXPERIMENTAL_OUTPUT_DIR
            / "spa_lmp2_experimental_live_candidate_selected_zones_latency_speed_aware_plan.csv",
            ExperimentalLiveValidationPackConfig(
                variant_key="selected_zones_latency_v2",
                recommended_run_nickname="recommendation_execution_selected_latency_v2_01",
                planned_lico_profile_id="spa_exp_live_candidate_selected_latency_v2",
                planned_lico_profile_description=(
                    "Speed-aware pilot live validation candidate from "
                    "range_aware_selected_zones with latency compensation v2."
                ),
                warmup_lap_count=2,
                scored_lap_count=3,
                include_t14=False,
                pack_status="official_frozen_live_baseline",
                status_summary=(
                    "Official frozen static-live baseline after the successful "
                    "telemetry-enabled speed-aware validation run."
                ),
            ),
        ),
        (
            EXPERIMENTAL_OUTPUT_DIR
            / "spa_lmp2_experimental_live_candidate_all_eligible_latency_speed_aware_plan.csv",
            ExperimentalLiveValidationPackConfig(
                variant_key="all_eligible_latency_v2",
                recommended_run_nickname=(
                    "recommendation_execution_all_eligible_latency_v2_01"
                ),
                planned_lico_profile_id="spa_exp_live_candidate_all_eligible_latency_v2",
                planned_lico_profile_description=(
                    "Speed-aware pilot live validation candidate from "
                    "range_aware_all_eligible_zones with latency compensation v2."
                ),
                warmup_lap_count=1,
                scored_lap_count=3,
                include_t14=True,
                pack_status="secondary_comparison_variant",
                status_summary=(
                    "Secondary comparison live variant kept for optional follow-up "
                    "against the frozen selected-zones latency v2 baseline."
                ),
            ),
        ),
        (
            EXPERIMENTAL_OUTPUT_DIR
            / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_plan.csv",
            ExperimentalLiveValidationPackConfig(
                variant_key="selected_zones_latency_v2_guarded_preview",
                recommended_run_nickname=(
                    "recommendation_execution_selected_latency_v2_guarded_preview_01"
                ),
                planned_lico_profile_id="spa_exp_guarded_handoff_selected_latency_v2",
                planned_lico_profile_description=(
                    "Guarded adaptive between-laps follow-up candidate derived from "
                    "the validated selected-zones latency v2 baseline session."
                ),
                warmup_lap_count=1,
                scored_lap_count=4,
                include_t14=False,
                pack_status="adaptive_guarded_operator_preview_candidate",
                status_summary=(
                    "Operator-preview follow-up candidate derived from the guarded "
                    "adaptive lap 8 -> 9 handoff of "
                    "recommendation_execution_selected_latency_v2_02."
                ),
                operator_mode="adaptive_guarded_operator_preview",
                source_run_id="recommendation_execution_selected_latency_v2_02",
                source_plan_id=(
                    "experimental_live_candidate_range_aware_selected_zones_latency_v2"
                ),
                source_current_lap_number=8,
                source_next_lap_number=9,
            ),
        ),
    ]

    for plan_path, config in packs:
        output_dir = write_experimental_live_validation_pack(
            plan_path,
            config=config,
            output_dir=PACK_OUTPUT_DIR,
            protocol_doc_path=PROTOCOL_DOC_PATH,
            replay_validation_report_path=REPLAY_VALIDATION_REPORT_PATH,
            replanner_validation_report_path=REPLANNER_VALIDATION_REPORT_PATH,
        )
        print(f"Wrote pack: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
