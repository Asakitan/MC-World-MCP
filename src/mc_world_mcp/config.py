from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    root: Path
    world_name_override: str | None = None

    @property
    def server_properties(self) -> dict[str, str]:
        path = self.root / "server.properties"
        result: dict[str, str] = {}
        if not path.exists():
            return result
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key] = value
        return result

    @property
    def world(self) -> Path:
        return self.root / self.world_name

    @property
    def world_name(self) -> str:
        return self.world_name_override or self.server_properties.get("level-name", "world")

    @property
    def backup_root(self) -> Path:
        return self.root / "backup" / "mc_world_mcp"


def load_config() -> ServerConfig:
    env_root = os.environ.get("MC_SERVER_ROOT")
    if env_root:
        root = Path(env_root)
    else:
        cwd = Path.cwd()
        if (cwd / "server.properties").exists() and (cwd / "world").exists():
            root = cwd
        else:
            root = Path(__file__).resolve().parents[3]
    world_name = os.environ.get("MC_WORLD_NAME") or None
    return ServerConfig(root=root.resolve(), world_name_override=world_name)
