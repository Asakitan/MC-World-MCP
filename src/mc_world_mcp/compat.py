from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nbtlib

from .config import ServerConfig

JAVA_1_20_1_DATA_VERSION = 3465


@dataclass(frozen=True)
class WorldInfo:
    platform: str
    data_version: int | None
    support_level: str
    world_path: Path
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "data_version": self.data_version,
            "support_level": self.support_level,
            "world_path": str(self.world_path),
            "reason": self.reason,
        }


def detect_world_info(config: ServerConfig) -> WorldInfo:
    world = config.world
    if (world / "db").is_dir() or (world / "levelname.txt").exists():
        return WorldInfo(
            platform="bedrock",
            data_version=None,
            support_level="unsupported",
            world_path=world,
            reason="Bedrock LevelDB worlds are detected but not editable by this Java Anvil MCP.",
        )

    level_dat = world / "level.dat"
    if not level_dat.exists():
        return WorldInfo(
            platform="unknown",
            data_version=None,
            support_level="unsupported",
            world_path=world,
            reason="No Java level.dat was found at the selected world path.",
        )

    try:
        data = nbtlib.load(level_dat)
    except Exception as exc:
        return WorldInfo(
            platform="unknown",
            data_version=None,
            support_level="unsupported",
            world_path=world,
            reason=f"level.dat exists but could not be parsed as Java NBT: {exc}",
        )

    data_root = data.get("Data", data)
    raw_version = data_root.get("DataVersion", data.get("DataVersion"))
    data_version = int(raw_version) if raw_version is not None else None
    if data_version == JAVA_1_20_1_DATA_VERSION:
        support = "full_1_20_1"
        reason = "Java Anvil world with Minecraft 1.20.1 DataVersion 3465."
    else:
        support = "readonly_best_effort"
        reason = "Java Anvil world detected, but writes are only fully supported for DataVersion 3465."
    return WorldInfo("java_anvil", data_version, support, world, reason)


def assert_world_write_supported(config: ServerConfig) -> WorldInfo:
    info = detect_world_info(config)
    if info.support_level != "full_1_20_1":
        raise RuntimeError(
            "refusing world write: "
            f"platform={info.platform}, data_version={info.data_version}, "
            f"support_level={info.support_level}. {info.reason}"
        )
    return info


def with_support(config: ServerConfig, value: dict[str, Any] | list[Any]) -> dict[str, Any]:
    info = detect_world_info(config).as_dict()
    if isinstance(value, dict):
        return {**info, **value}
    return {**info, "value": value}
