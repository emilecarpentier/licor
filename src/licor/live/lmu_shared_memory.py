from __future__ import annotations

import ctypes
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes


LMU_SHARED_MEMORY_NAME = "LMU_Data"
LMU_SHARED_MEMORY_EVENT_NAME = "LMU_Data_Event"

_DEFAULT_LMU_INSTALL_ROOT = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate"
)
_WAIT_OBJECT_0 = 0x00000000
_WAIT_TIMEOUT = 0x00000102
_FILE_MAP_READ = 0x0004
_SYNCHRONIZE = 0x00100000
_PAGE_READWRITE = 0x04
@dataclass(frozen=True)
class LmuLiveEnvironment:
    install_root: Path
    settings_path: Path
    shared_memory_support_dir: Path
    shared_memory_header_path: Path
    external_plugins_enabled: bool | None
    webui_bind: str | None
    webui_port: int | None
    status_flags: tuple[str, ...]

    @property
    def is_ready_for_static_live_cues(self) -> bool:
        blocking_flags = {
            "missing_install_root",
            "missing_settings_json",
            "missing_shared_memory_support",
            "external_plugins_disabled",
        }
        return not any(flag in blocking_flags for flag in self.status_flags)


@dataclass(frozen=True)
class LmuLiveTelemetrySample:
    lap_number: int
    lap_distance_m: float
    ts: float
    elapsed_s: float | None = None
    fuel_level_l: float | None = None
    speed_kph: float | None = None
    throttle_pct: float | None = None
    brake_pct: float | None = None
    gear: int | None = None


def inspect_default_lmu_live_environment() -> LmuLiveEnvironment:
    return inspect_lmu_live_environment(install_root=_DEFAULT_LMU_INSTALL_ROOT)


def inspect_lmu_live_environment(
    *,
    install_root: str | Path,
    settings_path: str | Path | None = None,
) -> LmuLiveEnvironment:
    root = Path(install_root)
    resolved_settings_path = (
        Path(settings_path)
        if settings_path is not None
        else root / "UserData" / "player" / "Settings.JSON"
    )
    support_dir = root / "Support" / "SharedMemoryInterface"
    header_path = support_dir / "SharedMemoryInterface.hpp"

    flags: list[str] = []
    if not root.exists():
        flags.append("missing_install_root")
    if not resolved_settings_path.exists():
        flags.append("missing_settings_json")
    if not support_dir.exists() or not header_path.exists():
        flags.append("missing_shared_memory_support")

    settings_payload: dict[str, object] = {}
    if resolved_settings_path.exists():
        settings_payload = json.loads(resolved_settings_path.read_text(encoding="utf-8"))

    game_options = settings_payload.get("Game Options")
    if not isinstance(game_options, dict):
        game_options = {}

    external_plugins_enabled = _optional_bool(game_options.get("Enable external plugins"))
    if external_plugins_enabled is False:
        flags.append("external_plugins_disabled")

    webui_bind = _optional_string(
        game_options.get("WebUI bind", _find_setting_value(settings_payload, "WebUI bind"))
    )
    webui_port = _optional_int(
        game_options.get("WebUI port", _find_setting_value(settings_payload, "WebUI port"))
    )
    if webui_port is None:
        flags.append("missing_webui_port")

    return LmuLiveEnvironment(
        install_root=root,
        settings_path=resolved_settings_path,
        shared_memory_support_dir=support_dir,
        shared_memory_header_path=header_path,
        external_plugins_enabled=external_plugins_enabled,
        webui_bind=webui_bind,
        webui_port=webui_port,
        status_flags=tuple(flags),
    )


def probe_lmu_shared_memory_available(
    *,
    shared_memory_name: str = LMU_SHARED_MEMORY_NAME,
    event_name: str = LMU_SHARED_MEMORY_EVENT_NAME,
) -> tuple[bool, str]:
    try:
        reader = LMUSharedMemoryReader(
            shared_memory_name=shared_memory_name,
            event_name=event_name,
        )
    except OSError as exc:
        return False, str(exc)
    reader.close()
    return True, "shared memory opened successfully"


class LMUSharedMemoryReader:
    def __init__(
        self,
        *,
        shared_memory_name: str = LMU_SHARED_MEMORY_NAME,
        event_name: str = LMU_SHARED_MEMORY_EVENT_NAME,
    ) -> None:
        if os.name != "nt":
            raise OSError("LMU live shared memory is only supported on Windows")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.OpenFileMappingW.argtypes = [
            ctypes.c_uint32,
            wintypes.BOOL,
            ctypes.c_wchar_p,
        ]
        self._kernel32.OpenFileMappingW.restype = ctypes.c_void_p
        self._kernel32.MapViewOfFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_size_t,
        ]
        self._kernel32.MapViewOfFile.restype = ctypes.c_void_p
        self._kernel32.OpenEventW.argtypes = [
            ctypes.c_uint32,
            wintypes.BOOL,
            ctypes.c_wchar_p,
        ]
        self._kernel32.OpenEventW.restype = ctypes.c_void_p
        self._kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
        self._kernel32.UnmapViewOfFile.restype = wintypes.BOOL
        self._shared_memory_name = shared_memory_name
        self._event_name = event_name
        self._mapping_handle = self._open_file_mapping(shared_memory_name)
        self._view_handle = self._map_view(self._mapping_handle)
        self._event_handle = self._open_event(event_name)

    def close(self) -> None:
        if getattr(self, "_view_handle", None):
            self._kernel32.UnmapViewOfFile(ctypes.c_void_p(self._view_handle))
            self._view_handle = None
        if getattr(self, "_event_handle", None):
            self._kernel32.CloseHandle(ctypes.c_void_p(self._event_handle))
            self._event_handle = None
        if getattr(self, "_mapping_handle", None):
            self._kernel32.CloseHandle(ctypes.c_void_p(self._mapping_handle))
            self._mapping_handle = None

    def wait_for_update(self, timeout_ms: int = 250) -> bool:
        wait_result = self._kernel32.WaitForSingleObject(
            ctypes.c_void_p(self._event_handle),
            ctypes.c_uint32(timeout_ms),
        )
        if wait_result == _WAIT_OBJECT_0:
            return True
        if wait_result == _WAIT_TIMEOUT:
            return False
        raise OSError(f"WaitForSingleObject failed: {_last_error_message()}")

    def read_player_sample(self, *, timestamp_s: float | None = None) -> LmuLiveTelemetrySample | None:
        layout = self._copy_layout()
        telemetry = layout.data.telemetry
        if not telemetry.player_has_vehicle:
            return None
        player_idx = int(telemetry.player_vehicle_idx)
        active_vehicles = int(telemetry.active_vehicles)
        if player_idx < 0 or player_idx >= active_vehicles or player_idx >= len(telemetry.telem_info):
            return None

        player = telemetry.telem_info[player_idx]
        if player_idx >= int(layout.data.scoring.scoring_info.num_vehicles):
            return None
        player_scoring = layout.data.scoring.veh_scoring_info[player_idx]
        speed_ms = abs(float(player.local_vel.z))
        return LmuLiveTelemetrySample(
            lap_number=int(player.lap_number),
            lap_distance_m=float(player_scoring.lap_dist),
            ts=timestamp_s if timestamp_s is not None else time.time(),
            elapsed_s=float(player.elapsed_time),
            fuel_level_l=float(player.fuel),
            speed_kph=speed_ms * 3.6,
            throttle_pct=float(player.filtered_throttle) * 100.0,
            brake_pct=float(player.filtered_brake) * 100.0,
            gear=int(player.gear),
        )

    def read_next_player_sample(
        self,
        *,
        timeout_ms: int = 250,
    ) -> LmuLiveTelemetrySample | None:
        if not self.wait_for_update(timeout_ms=timeout_ms):
            return None
        return self.read_player_sample()

    def read_race_snapshot(self) -> dict[str, object]:
        """Diagnostic snapshot only; does not supply a HUD horizon or cue."""
        from licor.live.race_capture import extract_race_snapshot

        return extract_race_snapshot(self._copy_layout())

    def _copy_layout(self) -> "SharedMemoryLayout":
        layout = SharedMemoryLayout()
        ctypes.memmove(
            ctypes.addressof(layout),
            ctypes.c_void_p(self._view_handle),
            ctypes.sizeof(SharedMemoryLayout),
        )
        return layout

    def _open_file_mapping(self, shared_memory_name: str) -> int:
        handle = self._kernel32.OpenFileMappingW(
            ctypes.c_uint32(_FILE_MAP_READ),
            wintypes.BOOL(False),
            ctypes.c_wchar_p(shared_memory_name),
        )
        if not handle:
            raise OSError(
                f"Could not open LMU shared memory '{shared_memory_name}': {_last_error_message()}"
            )
        return int(handle)

    def _map_view(self, mapping_handle: int) -> int:
        view = self._kernel32.MapViewOfFile(
            ctypes.c_void_p(mapping_handle),
            ctypes.c_uint32(_FILE_MAP_READ),
            ctypes.c_uint32(0),
            ctypes.c_uint32(0),
            ctypes.c_size_t(ctypes.sizeof(SharedMemoryLayout)),
        )
        if not view:
            raise OSError(f"Could not map LMU shared memory view: {_last_error_message()}")
        return int(view)

    def _open_event(self, event_name: str) -> int:
        handle = self._kernel32.OpenEventW(
            ctypes.c_uint32(_SYNCHRONIZE),
            wintypes.BOOL(False),
            ctypes.c_wchar_p(event_name),
        )
        if not handle:
            raise OSError(f"Could not open LMU shared memory event '{event_name}': {_last_error_message()}")
        return int(handle)


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _optional_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _find_setting_value(settings_payload: dict[str, object], key: str) -> object | None:
    if key in settings_payload:
        return settings_payload[key]
    for value in settings_payload.values():
        if isinstance(value, dict) and key in value:
            return value[key]
    return None


def _last_error_message() -> str:
    code = ctypes.get_last_error()
    if code == 0:
        return "unknown error"
    return f"WinError {code}"


class TelemVect3(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("z", ctypes.c_double)]


class TelemWheelV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("suspension_deflection", ctypes.c_double),
        ("ride_height", ctypes.c_double),
        ("susp_force", ctypes.c_double),
        ("brake_temp", ctypes.c_double),
        ("brake_pressure", ctypes.c_double),
        ("rotation", ctypes.c_double),
        ("lateral_patch_vel", ctypes.c_double),
        ("longitudinal_patch_vel", ctypes.c_double),
        ("lateral_ground_vel", ctypes.c_double),
        ("longitudinal_ground_vel", ctypes.c_double),
        ("camber", ctypes.c_double),
        ("lateral_force", ctypes.c_double),
        ("longitudinal_force", ctypes.c_double),
        ("tire_load", ctypes.c_double),
        ("grip_fract", ctypes.c_double),
        ("pressure", ctypes.c_double),
        ("temperature", ctypes.c_double * 3),
        ("wear", ctypes.c_double),
        ("terrain_name", ctypes.c_char * 16),
        ("surface_type", ctypes.c_ubyte),
        ("flat", ctypes.c_bool),
        ("detached", ctypes.c_bool),
        ("static_undeflected_radius", ctypes.c_ubyte),
        ("vertical_tire_deflection", ctypes.c_double),
        ("wheel_y_location", ctypes.c_double),
        ("toe", ctypes.c_double),
        ("tire_carcass_temperature", ctypes.c_double),
        ("tire_inner_layer_temperature", ctypes.c_double * 3),
        ("optimal_temp", ctypes.c_float),
        ("compound_index", ctypes.c_ubyte),
        ("compound_type", ctypes.c_ubyte),
        ("expansion", ctypes.c_ubyte * 18),
    ]


class TelemInfoV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("vehicle_id", ctypes.c_long),
        ("delta_time", ctypes.c_double),
        ("elapsed_time", ctypes.c_double),
        ("lap_number", ctypes.c_long),
        ("lap_start_et", ctypes.c_double),
        ("vehicle_name", ctypes.c_char * 64),
        ("track_name", ctypes.c_char * 64),
        ("pos", TelemVect3),
        ("local_vel", TelemVect3),
        ("local_accel", TelemVect3),
        ("ori", TelemVect3 * 3),
        ("local_rot", TelemVect3),
        ("local_rot_accel", TelemVect3),
        ("gear", ctypes.c_long),
        ("engine_rpm", ctypes.c_double),
        ("engine_water_temp", ctypes.c_double),
        ("engine_oil_temp", ctypes.c_double),
        ("clutch_rpm", ctypes.c_double),
        ("unfiltered_throttle", ctypes.c_double),
        ("unfiltered_brake", ctypes.c_double),
        ("unfiltered_steering", ctypes.c_double),
        ("unfiltered_clutch", ctypes.c_double),
        ("filtered_throttle", ctypes.c_double),
        ("filtered_brake", ctypes.c_double),
        ("filtered_steering", ctypes.c_double),
        ("filtered_clutch", ctypes.c_double),
        ("steering_shaft_torque", ctypes.c_double),
        ("front_3rd_deflection", ctypes.c_double),
        ("rear_3rd_deflection", ctypes.c_double),
        ("front_wing_height", ctypes.c_double),
        ("front_ride_height", ctypes.c_double),
        ("rear_ride_height", ctypes.c_double),
        ("drag", ctypes.c_double),
        ("front_downforce", ctypes.c_double),
        ("rear_downforce", ctypes.c_double),
        ("fuel", ctypes.c_double),
        ("engine_max_rpm", ctypes.c_double),
        ("scheduled_stops", ctypes.c_ubyte),
        ("overheating", ctypes.c_bool),
        ("detached", ctypes.c_bool),
        ("headlights", ctypes.c_bool),
        ("dent_severity", ctypes.c_ubyte * 8),
        ("last_impact_et", ctypes.c_double),
        ("last_impact_magnitude", ctypes.c_double),
        ("last_impact_pos", TelemVect3),
        ("engine_torque", ctypes.c_double),
        ("current_sector", ctypes.c_long),
        ("speed_limiter", ctypes.c_ubyte),
        ("max_gears", ctypes.c_ubyte),
        ("front_tire_compound_index", ctypes.c_ubyte),
        ("rear_tire_compound_index", ctypes.c_ubyte),
        ("fuel_capacity", ctypes.c_double),
        ("front_flap_activated", ctypes.c_ubyte),
        ("rear_flap_activated", ctypes.c_ubyte),
        ("rear_flap_legal_status", ctypes.c_ubyte),
        ("ignition_starter", ctypes.c_ubyte),
        ("front_tire_compound_name", ctypes.c_char * 18),
        ("rear_tire_compound_name", ctypes.c_char * 18),
        ("speed_limiter_available", ctypes.c_ubyte),
        ("anti_stall_activated", ctypes.c_ubyte),
        ("unused", ctypes.c_ubyte * 2),
        ("visual_steering_wheel_range", ctypes.c_float),
        ("rear_brake_bias", ctypes.c_double),
        ("turbo_boost_pressure", ctypes.c_double),
        ("physics_to_graphics_offset", ctypes.c_float * 3),
        ("physical_steering_wheel_range", ctypes.c_float),
        ("delta_best", ctypes.c_double),
        ("battery_charge_fraction", ctypes.c_double),
        ("electric_boost_motor_torque", ctypes.c_double),
        ("electric_boost_motor_rpm", ctypes.c_double),
        ("electric_boost_motor_temperature", ctypes.c_double),
        ("electric_boost_water_temperature", ctypes.c_double),
        ("electric_boost_motor_state", ctypes.c_ubyte),
        ("lap_invalidated", ctypes.c_bool),
        ("abs_active", ctypes.c_bool),
        ("tc_active", ctypes.c_bool),
        ("speed_limiter_active", ctypes.c_bool),
        ("wiper_state", ctypes.c_uint8),
        ("tc", ctypes.c_uint8),
        ("tc_max", ctypes.c_uint8),
        ("tc_slip", ctypes.c_uint8),
        ("tc_slip_max", ctypes.c_uint8),
        ("tc_cut", ctypes.c_uint8),
        ("tc_cut_max", ctypes.c_uint8),
        ("abs_setting", ctypes.c_uint8),
        ("abs_max", ctypes.c_uint8),
        ("motor_map", ctypes.c_uint8),
        ("motor_map_max", ctypes.c_uint8),
        ("migration", ctypes.c_uint8),
        ("migration_max", ctypes.c_uint8),
        ("front_anti_sway", ctypes.c_uint8),
        ("front_anti_sway_max", ctypes.c_uint8),
        ("rear_anti_sway", ctypes.c_uint8),
        ("rear_anti_sway_max", ctypes.c_uint8),
        ("lift_and_coast_progress", ctypes.c_uint8),
        ("track_limits_steps", ctypes.c_uint8),
        ("regen", ctypes.c_float),
        ("soc", ctypes.c_float),
        ("virtual_energy", ctypes.c_float),
        ("time_gap_car_ahead", ctypes.c_float),
        ("time_gap_car_behind", ctypes.c_float),
        ("time_gap_place_ahead", ctypes.c_float),
        ("time_gap_place_behind", ctypes.c_float),
        ("vehicle_model", ctypes.c_char * 30),
        ("vehicle_class", ctypes.c_uint8),
        ("vehicle_championship", ctypes.c_uint8),
        ("expansion", ctypes.c_ubyte * 20),
        ("wheel", TelemWheelV01 * 4),
    ]


class VehicleScoringInfoV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("vehicle_id", ctypes.c_long),
        ("driver_name", ctypes.c_char * 32),
        ("vehicle_name", ctypes.c_char * 64),
        ("total_laps", ctypes.c_short),
        ("sector", ctypes.c_byte),
        ("finish_status", ctypes.c_byte),
        ("lap_dist", ctypes.c_double),
        ("path_lateral", ctypes.c_double),
        ("track_edge", ctypes.c_double),
        ("best_sector_1", ctypes.c_double),
        ("best_sector_2", ctypes.c_double),
        ("best_lap_time", ctypes.c_double),
        ("last_sector_1", ctypes.c_double),
        ("last_sector_2", ctypes.c_double),
        ("last_lap_time", ctypes.c_double),
        ("cur_sector_1", ctypes.c_double),
        ("cur_sector_2", ctypes.c_double),
        ("num_pitstops", ctypes.c_short),
        ("num_penalties", ctypes.c_short),
        ("is_player", ctypes.c_bool),
        ("control", ctypes.c_byte),
        ("in_pits", ctypes.c_bool),
        ("place", ctypes.c_ubyte),
        ("vehicle_class", ctypes.c_char * 32),
        ("time_behind_next", ctypes.c_double),
        ("laps_behind_next", ctypes.c_long),
        ("time_behind_leader", ctypes.c_double),
        ("laps_behind_leader", ctypes.c_long),
        ("lap_start_et", ctypes.c_double),
        ("pos", TelemVect3),
        ("local_vel", TelemVect3),
        ("local_accel", TelemVect3),
        ("ori", TelemVect3 * 3),
        ("local_rot", TelemVect3),
        ("local_rot_accel", TelemVect3),
        ("headlights", ctypes.c_ubyte),
        ("pit_state", ctypes.c_ubyte),
        ("server_scored", ctypes.c_ubyte),
        ("individual_phase", ctypes.c_ubyte),
        ("qualification", ctypes.c_long),
        ("time_into_lap", ctypes.c_double),
        ("estimated_lap_time", ctypes.c_double),
        ("pit_group", ctypes.c_char * 24),
        ("flag", ctypes.c_ubyte),
        ("under_yellow", ctypes.c_bool),
        ("count_lap_flag", ctypes.c_ubyte),
        ("in_garage_stall", ctypes.c_bool),
        ("upgrade_pack", ctypes.c_ubyte * 16),
        ("pit_lap_dist", ctypes.c_float),
        ("best_lap_sector_1", ctypes.c_float),
        ("best_lap_sector_2", ctypes.c_float),
        ("steam_id", ctypes.c_ulonglong),
        ("veh_filename", ctypes.c_char * 32),
        ("attack_mode", ctypes.c_short),
        ("fuel_fraction", ctypes.c_ubyte),
        ("drs_state", ctypes.c_bool),
        ("expansion", ctypes.c_ubyte * 4),
    ]


class ScoringInfoV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("track_name", ctypes.c_char * 64),
        ("session", ctypes.c_long),
        ("current_et", ctypes.c_double),
        ("end_et", ctypes.c_double),
        ("max_laps", ctypes.c_long),
        ("lap_dist", ctypes.c_double),
        ("results_stream", ctypes.c_void_p),
        ("num_vehicles", ctypes.c_long),
        ("game_phase", ctypes.c_ubyte),
        ("yellow_flag_state", ctypes.c_byte),
        ("sector_flag", ctypes.c_byte * 3),
        ("start_light", ctypes.c_ubyte),
        ("num_red_lights", ctypes.c_ubyte),
        ("in_realtime", ctypes.c_bool),
        ("player_name", ctypes.c_char * 32),
        ("plr_file_name", ctypes.c_char * 64),
        ("dark_cloud", ctypes.c_double),
        ("raining", ctypes.c_double),
        ("ambient_temp", ctypes.c_double),
        ("track_temp", ctypes.c_double),
        ("wind", TelemVect3),
        ("min_path_wetness", ctypes.c_double),
        ("max_path_wetness", ctypes.c_double),
        ("game_mode", ctypes.c_ubyte),
        ("is_password_protected", ctypes.c_bool),
        ("server_port", ctypes.c_ushort),
        ("server_public_ip", ctypes.c_ulong),
        ("max_players", ctypes.c_long),
        ("server_name", ctypes.c_char * 32),
        ("start_et", ctypes.c_float),
        ("avg_path_wetness", ctypes.c_double),
        ("session_time_remaining", ctypes.c_float),
        ("time_of_day", ctypes.c_float),
        ("is_fixed_setup", ctypes.c_bool),
        ("track_grip_level", ctypes.c_uint8),
        ("cloud_coverage", ctypes.c_uint8),
        ("track_limits_steps_per_penalty", ctypes.c_uint8),
        ("track_limits_steps_per_point", ctypes.c_uint8),
        ("expansion", ctypes.c_ubyte * 187),
        ("vehicle", ctypes.c_void_p),
    ]


class ApplicationStateV01(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("app_window", ctypes.c_void_p),
        ("width", ctypes.c_ulong),
        ("height", ctypes.c_ulong),
        ("refresh_rate", ctypes.c_ulong),
        ("windowed", ctypes.c_ulong),
        ("options_location", ctypes.c_ubyte),
        ("options_page", ctypes.c_char * 31),
        ("expansion", ctypes.c_ubyte * 204),
    ]


class SharedMemoryGeneric(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("events", ctypes.c_uint32 * 16),
        ("game_version", ctypes.c_long),
        ("ffb_torque", ctypes.c_float),
        ("app_info", ApplicationStateV01),
    ]


class SharedMemoryPathData(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("user_data", ctypes.c_char * 260),
        ("custom_variables", ctypes.c_char * 260),
        ("steward_results", ctypes.c_char * 260),
        ("player_profile", ctypes.c_char * 260),
        ("plugins_folder", ctypes.c_char * 260),
    ]


class SharedMemoryScoringData(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("scoring_info", ScoringInfoV01),
        ("scoring_stream_size_raw", ctypes.c_ubyte * 12),
        ("veh_scoring_info", VehicleScoringInfoV01 * 104),
        ("scoring_stream", ctypes.c_char * 65536),
    ]


class SharedMemoryTelemetryData(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("active_vehicles", ctypes.c_ubyte),
        ("player_vehicle_idx", ctypes.c_ubyte),
        ("player_has_vehicle", ctypes.c_bool),
        ("telem_info", TelemInfoV01 * 104),
    ]


class SharedMemoryObjectOut(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("generic", SharedMemoryGeneric),
        ("paths", SharedMemoryPathData),
        ("scoring", SharedMemoryScoringData),
        ("telemetry", SharedMemoryTelemetryData),
    ]


class SharedMemoryLayout(ctypes.Structure):
    _pack_ = 4
    _fields_ = [("data", SharedMemoryObjectOut)]


assert ctypes.sizeof(ApplicationStateV01) == 260
assert ctypes.sizeof(ScoringInfoV01) == 548
