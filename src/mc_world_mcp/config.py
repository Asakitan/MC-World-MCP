from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    root: Path

    @property
    def world(self) -> Path:
        return self.root / "world"

    @property
    def backup_root(self) -> Path:
        return self.root / "backup" / "mc_world_mcp"


def load_config() -> ServerConfig:
    env_root = os.environ.get("MC_SERVER_ROOT")
    if env_root:
        root = Path(env_root)
    else:
        root = Path(__file__).resolve().parents[3]
    return ServerConfig(root=root.resolve())

