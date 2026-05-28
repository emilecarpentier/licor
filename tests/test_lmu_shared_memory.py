import ctypes
import json
from pathlib import Path

from licor.live.lmu_shared_memory import (
    ApplicationStateV01,
    ScoringInfoV01,
    inspect_lmu_live_environment,
)


def test_inspect_lmu_live_environment_reads_expected_flags(tmp_path: Path):
    install_root = tmp_path / "Le Mans Ultimate"
    support_dir = install_root / "Support" / "SharedMemoryInterface"
    support_dir.mkdir(parents=True)
    (support_dir / "SharedMemoryInterface.hpp").write_text("// stub", encoding="utf-8")
    settings_path = install_root / "UserData" / "player" / "Settings.JSON"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "Game Options": {
                    "Enable external plugins": True,
                    "WebUI bind": "localhost",
                    "WebUI port": 6397,
                }
            }
        ),
        encoding="utf-8",
    )

    environment = inspect_lmu_live_environment(
        install_root=install_root,
        settings_path=settings_path,
    )

    assert environment.is_ready_for_static_live_cues
    assert environment.external_plugins_enabled is True
    assert environment.webui_port == 6397
    assert environment.status_flags == ()


def test_inspect_lmu_live_environment_flags_disabled_plugins(tmp_path: Path):
    install_root = tmp_path / "Le Mans Ultimate"
    support_dir = install_root / "Support" / "SharedMemoryInterface"
    support_dir.mkdir(parents=True)
    (support_dir / "SharedMemoryInterface.hpp").write_text("// stub", encoding="utf-8")
    settings_path = install_root / "UserData" / "player" / "Settings.JSON"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps({"Game Options": {"Enable external plugins": False}}),
        encoding="utf-8",
    )

    environment = inspect_lmu_live_environment(
        install_root=install_root,
        settings_path=settings_path,
    )

    assert not environment.is_ready_for_static_live_cues
    assert "external_plugins_disabled" in environment.status_flags
    assert "missing_webui_port" in environment.status_flags


def test_critical_lmu_struct_sizes_match_known_values():
    assert ctypes.sizeof(ApplicationStateV01) == 260
    assert ctypes.sizeof(ScoringInfoV01) == 548
