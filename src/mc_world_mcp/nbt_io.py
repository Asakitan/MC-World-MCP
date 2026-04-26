from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any

import nbtlib

from .config import ServerConfig
from .paths import resolve_under_root
from .safety import begin_write


PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def tag_to_plain(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    if depth > max_depth:
        return "<max-depth>"
    if isinstance(value, nbtlib.Compound):
        return {str(k): tag_to_plain(v, depth + 1, max_depth) for k, v in value.items()}
    if isinstance(value, nbtlib.List):
        return [tag_to_plain(v, depth + 1, max_depth) for v in list(value)[:200]]
    if hasattr(value, "unpack"):
        try:
            return value.unpack()
        except Exception:
            return str(value)
    return value


def parse_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    if not path:
        return tokens
    for part in path.split("."):
        pos = 0
        for match in PATH_TOKEN.finditer(part):
            if match.start() != pos:
                raise ValueError(f"invalid NBT path segment: {part}")
            if match.group(1) is not None:
                tokens.append(match.group(1))
            else:
                tokens.append(int(match.group(2)))
            pos = match.end()
        if pos != len(part):
            raise ValueError(f"invalid NBT path segment: {part}")
    return tokens


def get_at_path(root: Any, path: str) -> Any:
    node = root
    for token in parse_path(path):
        node = node[token]
    return node


def set_at_path(root: Any, path: str, value: Any) -> None:
    tokens = parse_path(path)
    if not tokens:
        raise ValueError("path is required for writes")
    node = root
    for token in tokens[:-1]:
        node = node[token]
    node[tokens[-1]] = value


def load_nbt(path: Path):
    return nbtlib.load(path)


def dump_nbt_value(value: Any, *, max_depth: int = 5) -> str:
    return json.dumps(
        {
            "json": tag_to_plain(value, max_depth=max_depth),
            "snbt": value.snbt() if hasattr(value, "snbt") else str(value),
        },
        ensure_ascii=False,
        indent=2,
    )


def list_nbt_files(config: ServerConfig) -> list[dict[str, Any]]:
    roots = [
        config.world / "level.dat",
        config.world / "playerdata",
        config.world / "data",
        config.world / "datapacks",
    ]
    results: list[dict[str, Any]] = []
    for root in roots:
        if root.is_file() and root.suffix == ".dat":
            results.append(_info(config, root))
        elif root.is_dir():
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in (".dat", ".nbt"):
                    results.append(_info(config, path))
    return results


def _info(config: ServerConfig, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(config.root).as_posix(),
        "size": path.stat().st_size,
    }


def read_nbt_file(config: ServerConfig, relative_path: str, path: str = "", max_depth: int = 5) -> str:
    target = resolve_under_root(config, relative_path)
    data = load_nbt(target)
    value = get_at_path(data, path) if path else data
    return dump_nbt_value(value, max_depth=max_depth)


def write_nbt_value(config: ServerConfig, relative_path: str, path: str, snbt_value: str) -> str:
    target = resolve_under_root(config, relative_path, write=True)
    data = load_nbt(target)
    value = nbtlib.parse_nbt(snbt_value)
    set_at_path(data, path, value)
    backup = begin_write(config, f"write_nbt_value {relative_path} {path}", [target])
    data.save(target)
    backup.write_manifest()
    return json.dumps({"ok": True, "backup": str(backup.root)}, ensure_ascii=False)


def parse_chunk_nbt(raw: bytes):
    return nbtlib.File.parse(io.BytesIO(raw))


def write_chunk_nbt(nbt_file) -> bytes:
    buf = io.BytesIO()
    nbt_file.write(buf)
    return buf.getvalue()

