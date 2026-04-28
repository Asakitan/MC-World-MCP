from __future__ import annotations

from pathlib import Path

from .config import ServerConfig


READ_PREFIXES = (
    "server.properties",
    "logs",
    "config",
    "datapacks",
    "global_packs",
    "mods",
    "plugins",
    "resourcepacks",
    "world",
    "backup/mc_world_mcp",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
    "usercache.json",
    "usernamecache.json",
)

WRITE_PREFIXES = (
    "server.properties",
    "config",
    "datapacks",
    "global_packs",
    "world",
    "backup/mc_world_mcp",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
)


def rel_string(path: str | Path, config: ServerConfig | None = None) -> str:
    target = Path(path)
    if config is not None and target.is_absolute():
        try:
            return target.resolve().relative_to(config.root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError(f"path escapes MC_SERVER_ROOT: {path}") from exc
    return target.as_posix().lstrip("/")


def resolve_under_root(config: ServerConfig, relative_path: str | Path, *, write: bool = False) -> Path:
    rel = rel_string(relative_path, config)
    allowed = list(WRITE_PREFIXES if write else READ_PREFIXES)
    if config.world_name not in allowed:
        allowed.append(config.world_name)
    if not any(rel == p or rel.startswith(p + "/") for p in allowed):
        raise ValueError(f"path is not in the {'write' if write else 'read'} allowlist: {rel}")
    target = (config.root / rel).resolve()
    try:
        target.relative_to(config.root)
    except ValueError as exc:
        raise ValueError(f"path escapes MC_SERVER_ROOT: {relative_path}") from exc
    return target


def world_dimension_path(config: ServerConfig, dimension: str) -> Path:
    if dimension in ("overworld", "minecraft:overworld", ""):
        return config.world
    if dimension in ("nether", "minecraft:the_nether", "DIM-1"):
        return config.world / "DIM-1"
    if dimension in ("end", "minecraft:the_end", "DIM1"):
        return config.world / "DIM1"
    raise ValueError("dimension must be overworld, nether, or end")
