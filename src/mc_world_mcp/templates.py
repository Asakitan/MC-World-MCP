from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

import nbtlib

from .anvil import RegionFile, get_block, load_chunk_with_cache, region_coords, set_block_in_chunk
from .config import ServerConfig
from .nbt_io import parse_chunk_nbt, read_nbt_file, write_chunk_nbt, write_nbt_value
from .paths import resolve_under_root
from .safety import begin_write
from .world_ops import _entity_region_root, _iter_region_chunks


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
    block_entities_by_pos: dict[tuple[int, int, int], Any] = {}
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], Any] = {}
    for x in range(min_x, max_x + 1):
        for z in range(min_z, max_z + 1):
            key = (x >> 4, z >> 4)
            if key not in chunks:
                chunks[key] = load_chunk_with_cache(config, key[0], key[1], dimension, regions)[3]
    for chunk in chunks.values():
        for block_entity in chunk.get("block_entities", []):
            bx, by, bz = int(block_entity.get("x", 0)), int(block_entity.get("y", 0)), int(block_entity.get("z", 0))
            if min_x <= bx <= max_x and min_y <= by <= max_y and min_z <= bz <= max_z:
                block_entities_by_pos[(bx, by, bz)] = block_entity
    for y in range(min_y, max_y + 1):
        for z in range(min_z, max_z + 1):
            for x in range(min_x, max_x + 1):
                block = get_block(config, x, y, z, dimension)
                if block == "minecraft:air":
                    continue
                if block not in palette_index:
                    palette_index[block] = len(palette)
                    palette.append(block)
                block_entry = nbtlib.Compound({
                    "pos": nbtlib.List[nbtlib.Int]([nbtlib.Int(x - min_x), nbtlib.Int(y - min_y), nbtlib.Int(z - min_z)]),
                    "state": nbtlib.Int(palette_index[block]),
                })
                block_entity = block_entities_by_pos.get((x, y, z))
                if block_entity is not None:
                    be_copy = copy.deepcopy(block_entity)
                    be_copy.pop("x", None)
                    be_copy.pop("y", None)
                    be_copy.pop("z", None)
                    block_entry["nbt"] = be_copy
                blocks.append(block_entry)
    nbt_palette = nbtlib.List[nbtlib.Compound]([
        nbtlib.Compound({"Name": nbtlib.String(block)}) for block in palette
    ])
    entities = nbtlib.List[nbtlib.Compound]()
    entity_root = _entity_region_root(config, dimension)
    if entity_root.exists():
        for _, _, _, _, _, chunk in _iter_region_chunks(entity_root):
            for entity in chunk.get("Entities", []):
                pos = entity.get("Pos", [])
                if len(pos) != 3:
                    continue
                ex, ey, ez = float(pos[0]), float(pos[1]), float(pos[2])
                if min_x <= ex <= max_x + 1 and min_y <= ey <= max_y + 1 and min_z <= ez <= max_z + 1:
                    entity_copy = copy.deepcopy(entity)
                    entity_copy["Pos"] = nbtlib.List[nbtlib.Double]([
                        nbtlib.Double(ex - min_x),
                        nbtlib.Double(ey - min_y),
                        nbtlib.Double(ez - min_z),
                    ])
                    entities.append(nbtlib.Compound({
                        "pos": nbtlib.List[nbtlib.Double]([
                            nbtlib.Double(ex - min_x),
                            nbtlib.Double(ey - min_y),
                            nbtlib.Double(ez - min_z),
                        ]),
                        "blockPos": nbtlib.List[nbtlib.Int]([
                            nbtlib.Int(int(ex) - min_x),
                            nbtlib.Int(int(ey) - min_y),
                            nbtlib.Int(int(ez) - min_z),
                        ]),
                        "nbt": entity_copy,
                    }))
    root = nbtlib.File({
        "DataVersion": nbtlib.Int(3465),
        "size": nbtlib.List[nbtlib.Int]([nbtlib.Int(sx), nbtlib.Int(sy), nbtlib.Int(sz)]),
        "palette": nbt_palette,
        "blocks": blocks,
        "entities": entities,
    })
    backup = begin_write(config, f"export_region_to_template {output_path}", [target])
    target.parent.mkdir(parents=True, exist_ok=True)
    root.save(target, gzipped=True)
    backup.write_manifest()
    return json.dumps({"ok": True, "blocks": len(blocks), "entities": len(entities), "palette": len(palette), "backup": str(backup.root)}, ensure_ascii=False)


def place_template_to_region(config: ServerConfig, template_path: str, x: int, y: int, z: int, dimension: str = "overworld", confirm: bool = False) -> str:
    target = resolve_under_root(config, template_path)
    template = nbtlib.load(target)
    blocks = template.get("blocks", [])
    if len(blocks) > 4096 and not confirm:
        raise ValueError("large template placement requires confirm=true")
    palette = template.get("palette", [])
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    placements: list[tuple[int, int, int, str, Any | None]] = []
    entity_regions: dict[Path, RegionFile] = {}
    entity_chunks: dict[tuple[Path, int], Any] = {}
    entity_targets: list[tuple[Path, int, Any]] = []
    changed = 0
    for block in blocks:
        state = int(block["state"])
        block_id = _palette_entry_to_string(palette[state])
        pos = block["pos"]
        wx, wy, wz = x + int(pos[0]), y + int(pos[1]), z + int(pos[2])
        placements.append((wx, wy, wz, block_id, block.get("nbt")))
        key = (wx >> 4, wz >> 4)
        if key not in chunks:
            chunks[key] = load_chunk_with_cache(config, key[0], key[1], dimension, regions)
    for entity_entry in template.get("entities", []):
        entity_nbt = copy.deepcopy(entity_entry.get("nbt"))
        if entity_nbt is None:
            continue
        rel_pos = entity_entry.get("pos", entity_nbt.get("Pos", []))
        if len(rel_pos) != 3:
            continue
        wxp, wyp, wzp = x + float(rel_pos[0]), y + float(rel_pos[1]), z + float(rel_pos[2])
        entity_nbt["Pos"] = nbtlib.List[nbtlib.Double]([nbtlib.Double(wxp), nbtlib.Double(wyp), nbtlib.Double(wzp)])
        cx, cz = int(wxp) >> 4, int(wzp) >> 4
        eroot = _entity_region_root(config, dimension)
        rx, rz, eindex = region_coords(cx, cz)
        epath = eroot / f"r.{rx}.{rz}.mca"
        if not epath.exists():
            continue
        eregion = entity_regions.setdefault(epath, RegionFile(epath))
        key = (epath, eindex)
        if key not in entity_chunks:
            raw = eregion.get_raw(eindex)
            if raw is None:
                continue
            entity_chunks[key] = parse_chunk_nbt(raw)
        entity_targets.append((epath, eindex, entity_nbt))
    backup_files = sorted({item[0] for item in chunks.values()} | set(entity_regions))
    backup = begin_write(config, f"place_template_to_region {template_path}", backup_files)
    for wx, wy, wz, block_id, block_nbt in placements:
        _, _, _, chunk = chunks[(wx >> 4, wz >> 4)]
        before = set_block_in_chunk(chunk, wx, wy, wz, block_id)
        if before != block_id:
            changed += 1
        if block_nbt is not None:
            block_entities = chunk.setdefault("block_entities", nbtlib.List[nbtlib.Compound]())
            kept = nbtlib.List[nbtlib.Compound]([
                item for item in block_entities
                if not (int(item.get("x", 0)) == wx and int(item.get("y", 0)) == wy and int(item.get("z", 0)) == wz)
            ])
            be_copy = copy.deepcopy(block_nbt)
            be_copy["x"] = nbtlib.Int(wx)
            be_copy["y"] = nbtlib.Int(wy)
            be_copy["z"] = nbtlib.Int(wz)
            kept.append(be_copy)
            chunk["block_entities"] = kept
    for _, region, index, chunk in chunks.values():
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in regions.values():
        region.write()
    backup.write_manifest()
    # Entity placement is best effort and only appends to existing entity chunks.
    placed_entities = 0
    for epath, eindex, entity_nbt in entity_targets:
        eregion = entity_regions[epath]
        echunk = entity_chunks[(epath, eindex)]
        echunk.setdefault("Entities", nbtlib.List[nbtlib.Compound]()).append(entity_nbt)
        eregion.set_raw(eindex, write_chunk_nbt(echunk))
        placed_entities += 1
    for eregion in entity_regions.values():
        eregion.write()
    return json.dumps({"ok": True, "placed_blocks": changed, "placed_entities": placed_entities, "backup": str(backup.root)}, ensure_ascii=False)


def _palette_entry_to_string(entry) -> str:
    name = str(entry.get("Name", "minecraft:air"))
    props = entry.get("Properties")
    if not props:
        return name
    return f"{name}[{','.join(f'{key}={props[key]}' for key in sorted(props))}]"
