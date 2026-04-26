from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import nbtlib

from .anvil import get_block, set_block
from .config import ServerConfig
from .nbt_io import read_nbt_file, write_nbt_value
from .paths import resolve_under_root
from .safety import begin_write


def list_structure_templates(config: ServerConfig) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    roots = [config.world / "datapacks", config.world / "generated", config.root / "config"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.nbt"):
            results.append({
                "path": path.relative_to(config.root).as_posix(),
                "size": path.stat().st_size,
            })
    return results


def read_structure_template(config: ServerConfig, relative_path: str, nbt_path: str = "") -> str:
    return read_nbt_file(config, relative_path, nbt_path, max_depth=7)


def write_structure_template_value(config: ServerConfig, relative_path: str, nbt_path: str, snbt_value: str) -> str:
    return write_nbt_value(config, relative_path, nbt_path, snbt_value)


def write_structure_template(config: ServerConfig, relative_path: str, raw_bytes_base16: str) -> str:
    target = resolve_under_root(config, relative_path, write=True)
    if target.suffix != ".nbt":
        raise ValueError("structure template path must end in .nbt")
    backup = begin_write(config, f"write_structure_template {relative_path}", [target])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes.fromhex(raw_bytes_base16))
    backup.write_manifest()
    return json.dumps({"ok": True, "backup": str(backup.root)}, ensure_ascii=False)


def export_region_to_template(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, output_path: str, dimension: str = "overworld", confirm: bool = False) -> str:
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    min_z, max_z = sorted((z1, z2))
    sx, sy, sz = max_x - min_x + 1, max_y - min_y + 1, max_z - min_z + 1
    count = sx * sy * sz
    if count > 4096 and not confirm:
        raise ValueError("large template export requires confirm=true")
    target = resolve_under_root(config, output_path, write=True)
    if target.suffix != ".nbt":
        raise ValueError("output_path must end in .nbt")
    palette: list[str] = []
    palette_index: dict[str, int] = {}
    blocks = nbtlib.List[nbtlib.Compound]()
    for y in range(min_y, max_y + 1):
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                block = get_block(config, x, y, z, dimension)
                if block == "minecraft:air":
                    continue
                if block not in palette_index:
                    palette_index[block] = len(palette)
                    palette.append(block)
                blocks.append(nbtlib.Compound({
                    "pos": nbtlib.List[nbtlib.Int]([nbtlib.Int(x - min_x), nbtlib.Int(y - min_y), nbtlib.Int(z - min_z)]),
                    "state": nbtlib.Int(palette_index[block]),
                }))
    nbt_palette = nbtlib.List[nbtlib.Compound]([
        nbtlib.Compound({"Name": nbtlib.String(block)}) for block in palette
    ])
    root = nbtlib.File({
        "DataVersion": nbtlib.Int(3465),
        "size": nbtlib.List[nbtlib.Int]([nbtlib.Int(sx), nbtlib.Int(sy), nbtlib.Int(sz)]),
        "palette": nbt_palette,
        "blocks": blocks,
        "entities": nbtlib.List[nbtlib.Compound](),
    })
    backup = begin_write(config, f"export_region_to_template {output_path}", [target])
    target.parent.mkdir(parents=True, exist_ok=True)
    root.save(target, gzipped=True)
    backup.write_manifest()
    return json.dumps({"ok": True, "blocks": len(blocks), "palette": len(palette), "backup": str(backup.root)}, ensure_ascii=False)


def place_template_to_region(config: ServerConfig, template_path: str, x: int, y: int, z: int, dimension: str = "overworld", confirm: bool = False) -> str:
    target = resolve_under_root(config, template_path)
    template = nbtlib.load(target)
    blocks = template.get("blocks", [])
    if len(blocks) > 4096 and not confirm:
        raise ValueError("large template placement requires confirm=true")
    palette = template.get("palette", [])
    changed = 0
    for block in blocks:
        state = int(block["state"])
        block_id = str(palette[state]["Name"])
        pos = block["pos"]
        set_block(config, x + int(pos[0]), y + int(pos[1]), z + int(pos[2]), block_id, dimension)
        changed += 1
    return json.dumps({"ok": True, "placed_blocks": changed}, ensure_ascii=False)
