"""Causal native-race diagnostics, never an authoritative fuel horizon.

The constant-pace forecast is emitted only at observed player lap crossings.
An uncalibrated point forecast cannot supply the fuel budget's upper horizon.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from licor.analysis.race_scenarios import leader_lap_switch


def _finite(value) -> bool:
    return (
        isinstance(value, (float, int))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _state(row: dict) -> str:
    player = row.get("player") or {}
    if row.get("status") != "matched" or not player:
        return "unavailable"
    if not _count(row.get("session")) or not 10 <= row["session"] <= 13:
        return "not_race"
    if player.get("in_garage"):
        return "garage"
    if not row.get("in_realtime") or row.get("game_phase") == 9:
        return "paused"
    if player.get("finish_status") == 1:
        return "player_finished"
    if player.get("finish_status") in (2, 3):
        return "retired"
    if row.get("game_phase") == 3:
        return "formation"
    if row.get("game_phase") in (0, 1, 2, 4):
        return "pre_start"
    if row.get("game_phase") == 6:
        return "caution"
    if row.get("game_phase") == 7:
        return "stopped"
    if row.get("game_phase") not in (5, 8):
        return "unavailable"
    if player.get("in_pits"):
        return "pit"
    if (row.get("leader") or {}).get("finish_status") == 1:
        return "leader_finished"
    if row["game_phase"] == 8:
        return "session_over_unconfirmed_player"
    remaining = row.get("session_time_remaining_s")
    if _finite(remaining) and remaining <= 0:
        return "clock_expired"
    return "racing"


def replay_race_context(samples: Iterable[dict]) -> list[dict]:
    """Process each row once; future samples never revise earlier outputs.

    Histories reset on an inactive/unknown state, identity change, clock/lap
    rollback, refuel, skipped player lap, >1 s recording gap or >1 s frozen
    scoring clock (5 Hz input). Fuel increases >0.01 L are reset diagnostics,
    not certified refueling events.
    Crossing times are first observed scoring timestamps, not interpolated
    future-informed crossings. No clean-lap or executed-action inference.
    """
    outputs = []
    previous = None
    last_capture = None
    last_native_et = last_native_change_capture = None
    context = 0
    player_cross = leader_cross = player_pace = leader_pace = None
    active_states = {
        "racing",
        "clock_expired",
        "leader_finished",
        "session_over_unconfirmed_player",
        "player_finished",
    }
    for row in samples:
        capture = row.get("capture_elapsed_s")
        if (
            not _finite(capture)
            or capture < 0
            or (last_capture is not None and capture <= last_capture)
        ):
            raise ValueError("capture_elapsed_s must be finite and strictly increasing")
        last_capture = capture
        player = row.get("player") or {}
        leader = row.get("leader") or {}
        now = row.get("scoring_elapsed_s")
        laps = player.get("completed_laps")
        state = _state(row)
        if _finite(now) and now != last_native_et:
            last_native_et, last_native_change_capture = now, capture
        if (
            state in active_states
            and last_native_change_capture is not None
            and capture - last_native_change_capture > 1.0
        ):
            state = "stale_scoring"
        active = (
            state in active_states
            and _finite(now)
            and now >= 0
            and _count(laps)
            and _count(player.get("vehicle_id"))
            and bool(row.get("track"))
        )
        if state in active_states and not active:
            state = "unavailable"
        identity = (row.get("track"), row.get("session"), player.get("vehicle_id"))
        reset = None
        if not active:
            reset = "inactive_or_unavailable"
        elif previous is None:
            reset = "active_context_start"
        else:
            old = previous["player"]
            old_identity = (
                previous.get("track"),
                previous.get("session"),
                old.get("vehicle_id"),
            )
            if identity != old_identity:
                reset = "identity_changed"
            elif now < previous["scoring_elapsed_s"] or laps < old["completed_laps"]:
                reset = "native_clock_or_lap_rollback"
            elif now == previous["scoring_elapsed_s"] and laps > old["completed_laps"]:
                reset = "counter_advance_without_clock_progress"
            elif capture - previous["capture_elapsed_s"] > 1.0:
                reset = "recording_gap"
            elif laps > old["completed_laps"] + 1:
                reset = "skipped_player_lap"
            elif (
                _finite(player.get("fuel_l"))
                and _finite(old.get("fuel_l"))
                and player["fuel_l"] > old["fuel_l"] + 0.01
            ):
                reset = "fuel_increase"
        if reset:
            player_cross = leader_cross = player_pace = leader_pace = None
            previous = None
            if active:
                context += 1

        boundary = False
        if active and previous is not None:
            if laps == previous["player"]["completed_laps"] + 1:
                boundary = True
                if player_cross is not None and now > player_cross:
                    player_pace = now - player_cross
                player_cross = now
            old_leader = previous.get("leader") or {}
            if not _count(leader.get("vehicle_id")) or leader.get(
                "vehicle_id"
            ) != old_leader.get("vehicle_id"):
                leader_cross = leader_pace = None
            elif _count(leader.get("completed_laps")) and _count(
                old_leader.get("completed_laps")
            ):
                delta = leader["completed_laps"] - old_leader["completed_laps"]
                if delta == 1 and now > previous["scoring_elapsed_s"]:
                    if leader_cross is not None and now > leader_cross:
                        leader_pace = now - leader_cross
                    leader_cross = now
                elif delta != 0:
                    leader_cross = leader_pace = None
            else:
                leader_cross = leader_pace = None

        nominal = upper = predicted_finish = None
        switch = None
        reason = "abstain_not_player_boundary"
        if state == "player_finished":
            nominal = upper = 0
            reason = "observed_player_finish"
        elif not active:
            reason = "abstain_inactive_or_unavailable"
        elif boundary:
            remaining = row.get("session_time_remaining_s")
            if state not in {"racing", "clock_expired"}:
                reason = "abstain_await_player_finish"
            elif not _finite(remaining) or remaining < 0:
                reason = "abstain_missing_timer"
            elif player_pace is None or leader_pace is None:
                reason = "abstain_insufficient_past_crossings"
            elif now - leader_cross > leader_pace + 1.0:
                # One second of capture/scoring tolerance, not a calibrated
                # pace envelope. A slow/stopped or stale leader is ambiguous.
                reason = "abstain_overdue_leader_crossing"
            else:
                # Explicit prototype convention: first leader crossing strictly
                # after timer expiry, with both cars keeping last observed pace.
                timer_end = now + remaining
                leader_laps = max(
                    1, math.floor((timer_end - leader_cross) / leader_pace) + 1
                )
                predicted_finish = leader_cross + leader_laps * leader_pace
                nominal = max(1, math.ceil((predicted_finish - now) / player_pace))
                reason = "diagnostic_constant_pace_only"
                # Compare the adjacent leader totals around the nearest timer
                # crossing. These are not automatically the player's totals.
                short_crossings = leader_laps
                if leader_laps > 1 and abs(
                    predicted_finish - leader_pace - timer_end
                ) < abs(predicted_finish - timer_end):
                    short_crossings -= 1
                next_crossing = leader_cross + leader_pace - now
                if next_crossing >= 0:
                    switch = leader_lap_switch(
                        remaining_time_s=remaining,
                        seconds_to_next_crossing=next_crossing,
                        completed_leader_laps=leader["completed_laps"],
                        leader_pace_s=leader_pace,
                        short_total_leader_laps=leader["completed_laps"]
                        + short_crossings,
                        timing_tolerance_s=1.0,
                    )
        outputs.append(
            {
                "capture_elapsed_s": capture,
                "scoring_elapsed_s": now,
                "context_id": context if active else None,
                "state": state,
                "context_reset_reason": reset,
                "completed_laps": laps,
                "observed_player_boundary": boundary,
                "fuel_l": player.get("fuel_l"),
                "hud_total_laps": row.get("hud_total_laps"),
                "hud_fuel_laps": row.get("hud_fuel_laps"),
                "licor_nominal_remaining_laps": nominal,
                "upper_remaining_laps": upper,
                "predicted_leader_finish_s": predicted_finish,
                "player_past_lap_s": player_pace,
                "leader_past_lap_s": leader_pace,
                "horizon_status": reason,
                "leader_switch": switch,
                "fuel_plan_authorized": False,
            }
        )
        previous = row if active else None
    return outputs
