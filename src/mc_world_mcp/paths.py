from __future__ import annotations

from pathlib import Path

from .config import ServerConfig


READ_PREFIXES = (
    "server.properties",
    "logs",
    "config",
    "mods",
    "plugins",
    "world",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
    "usercache.json",
    "usernamecache.json",
)

WRITE_PREFIXES = (
    "server.properties",
    "config",
    "world",
    "whitelist.json",
    "banned-players.json",
    "banned-ips.json",
)


def rel_string(path: str | Path) -> str:
    return Path(path).as_posix().lstrip("/")


def resolve_under_root(config: ServerConfig, relative_path: str | Path, *, write: bool = False) -> Path:
    rel = rel_string(relative_path)
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
