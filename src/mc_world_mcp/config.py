from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def _read_server_properties(root: Path) -> dict[str, str]:
    path = root / "server.properties"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def _is_server_root(path: Path) -> bool:
    return (path / "server.properties").is_file()


def _configured_world_name(root: Path, world_name: str | None = None) -> str:
    if world_name:
        return world_name
    return _read_server_properties(root).get("level-name", "world")


def _world_exists(root: Path, world_name: str | None = None) -> bool:
    return (root / _configured_world_name(root, world_name)).exists()


def discover_server_roots(search_root: str | Path, max_depth: int = 3) -> list[dict[str, Any]]:
    """Find likely Minecraft server roots below a local directory."""
    base = Path(search_root).expanduser().resolve()
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"search root does not exist or is not a directory: {base}")

    seen: set[Path] = set()
    results: list[dict[str, Any]] = []

    def visit(path: Path, depth: int) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        if _is_server_root(resolved):
            props = _read_server_properties(resolved)
            world_name = props.get("level-name", "world")
            world_path = resolved / world_name
            results.append({
                "server_root": str(resolved),
                "level_name": world_name,
                "world_path": str(world_path),
                "world_exists": world_path.exists(),
                "has_logs": (resolved / "logs").exists(),
                "has_mods": (resolved / "mods").exists(),
                "has_plugins": (resolved / "plugins").exists(),
            })
            return
        if depth >= max_depth:
            return
        try:
            children = [child for child in path.iterdir() if child.is_dir()]
        except OSError:
            return
        for child in sorted(children, key=lambda item: item.name.lower()):
            if child.name in {".git", ".venv", "node_modules", "__pycache__"}:
                continue
            visit(child, depth + 1)

    visit(base, 0)
    return results


def resolve_server_root(root: str | Path) -> Path:
    """Resolve a configured root, accepting a workspace that contains a server subdirectory."""
    path = Path(root).expanduser().resolve()
    if _is_server_root(path):
        return path
    child_server = path / "server"
    if _is_server_root(child_server):
        return child_server.resolve()
    candidates = discover_server_roots(path, max_depth=2) if path.exists() and path.is_dir() else []
    world_candidates = [Path(item["server_root"]) for item in candidates if item["world_exists"]]
    if len(world_candidates) == 1:
        return world_candidates[0].resolve()
    if len(candidates) == 1:
        return Path(candidates[0]["server_root"]).resolve()
    return path


def make_config(root: str | Path, world_name: str | None = None) -> ServerConfig:
    resolved_root = resolve_server_root(root)
    if world_name and Path(world_name).name != world_name:
        raise ValueError("world_name must be a local world directory name")
    return ServerConfig(root=resolved_root, world_name_override=world_name or None)


def load_config() -> ServerConfig:
    env_root = os.environ.get("MC_SERVER_ROOT")
    if env_root:
        root = resolve_server_root(env_root)
    else:
        cwd = Path.cwd()
        if (cwd / "server.properties").exists() and (cwd / "world").exists():
            root = cwd
        else:
            root = resolve_server_root(Path(__file__).resolve().parents[3])
    world_name = os.environ.get("MC_WORLD_NAME") or None
    return ServerConfig(root=root.resolve(), world_name_override=world_name)
