from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import nbtlib

from .anvil import RegionFile, region_coords, region_path, scan_regions
from .anvil import load_chunk_with_cache, set_block_in_chunk
from .compat import detect_world_info
from .config import ServerConfig
from .nbt_io import parse_chunk_nbt, set_at_path, write_chunk_nbt
from .paths import world_dimension_path
from .safety import begin_write


def list_dimensions(config: ServerConfig) -> list[dict[str, Any]]:
    candidates = [
        ("overworld", config.world),
        ("nether", config.world / "DIM-1"),
        ("end", config.world / "DIM1"),
    ]
    return [
        {
            "dimension": name,
            "path": path.relative_to(config.root).as_posix(),
            "exists": path.exists(),
            "region_files": len(list((path / "region").glob("*.mca"))) if (path / "region").exists() else 0,
            "entity_files": len(list((path / "entities").glob("*.mca"))) if (path / "entities").exists() else 0,
            "poi_files": len(list((path / "poi").glob("*.mca"))) if (path / "poi").exists() else 0,
        }
        for name, path in candidates
    ]


def scan_world_coverage(config: ServerConfig, dimension: str = "overworld") -> dict[str, Any]:
    regions = scan_regions(config, dimension)
    if not regions:
        return {"dimension": dimension, "region_count": 0, "chunk_count": 0}
    return {
        "dimension": dimension,
        "region_count": len(regions),
        "chunk_count": sum(item["chunks"] for item in regions),
        "rx_range": [min(item["rx"] for item in regions), max(item["rx"] for item in regions)],
        "rz_range": [min(item["rz"] for item in regions), max(item["rz"] for item in regions)],
        "regions": regions,
    }


def edit_block_entity(config: ServerConfig, x: int, y: int, z: int, nbt_path: str, snbt_value: str, dimension: str = "overworld") -> dict[str, Any]:
    cx, cz = x >> 4, z >> 4
    path, region, index, chunk = load_chunk_with_cache(config, cx, cz, dimension, {})
    for block_entity in chunk.get("block_entities", []):
        if int(block_entity.get("x", 0)) == x and int(block_entity.get("y", 0)) == y and int(block_entity.get("z", 0)) == z:
            set_at_path(block_entity, nbt_path, nbtlib.parse_nbt(snbt_value))
            backup = begin_write(config, f"edit_block_entity {x} {y} {z} {nbt_path}", [path])
            region.set_raw(index, write_chunk_nbt(chunk))
            region.write()
            backup.write_manifest()
            return {"ok": True, "backup": str(backup.root)}
    raise FileNotFoundError(f"block entity not found at {x},{y},{z}")


def write_chunk_nbt_value(config: ServerConfig, cx: int, cz: int, path: str, snbt_value: str, dimension: str = "overworld") -> dict[str, Any]:
    region_path_value, region, index, chunk = load_chunk_with_cache(config, cx, cz, dimension, {})
    set_at_path(chunk, path, nbtlib.parse_nbt(snbt_value))
    backup = begin_write(config, f"write_chunk_nbt_value {dimension} {cx} {cz} {path}", [region_path_value])
    region.set_raw(index, write_chunk_nbt(chunk))
    region.write()
    backup.write_manifest()
    return {"ok": True, "chunk": {"cx": cx, "cz": cz}, "path": path, "backup": str(backup.root)}


def add_block_entity(config: ServerConfig, x: int, y: int, z: int, block_state: str, block_entity_snbt: str, dimension: str = "overworld") -> dict[str, Any]:
    cx, cz = x >> 4, z >> 4
    region_path_value, region, index, chunk = load_chunk_with_cache(config, cx, cz, dimension, {})
    block_entity = nbtlib.parse_nbt(block_entity_snbt)
    if not isinstance(block_entity, nbtlib.Compound):
        raise ValueError("block_entity_snbt must be an SNBT compound")
    block_entity["x"] = nbtlib.Int(x)
    block_entity["y"] = nbtlib.Int(y)
    block_entity["z"] = nbtlib.Int(z)
    block_entities = chunk.setdefault("block_entities", nbtlib.List[nbtlib.Compound]())
    kept = nbtlib.List[nbtlib.Compound]([
        item for item in block_entities
        if not (int(item.get("x", 0)) == x and int(item.get("y", 0)) == y and int(item.get("z", 0)) == z)
    ])
    kept.append(block_entity)
    chunk["block_entities"] = kept
    backup = begin_write(config, f"add_block_entity {dimension} {x} {y} {z}", [region_path_value])
    before = set_block_in_chunk(chunk, x, y, z, block_state)
    region.set_raw(index, write_chunk_nbt(chunk))
    region.write()
    backup.write_manifest()
    return {
        "ok": True,
        "before": before,
        "after": block_state,
        "block_entity_count": len(kept),
        "backup": str(backup.root),
    }


def set_biome_box(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, biome: str, dimension: str = "overworld", confirm: bool = False) -> dict[str, Any]:
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    min_z, max_z = sorted((z1, z2))
    cells = ((max_x // 4) - (min_x // 4) + 1) * ((max_y // 4) - (min_y // 4) + 1) * ((max_z // 4) - (min_z // 4) + 1)
    if cells > 4096 and not confirm:
        raise ValueError("large biome edit requires confirm=true")
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    for cell_x in range(min_x // 4, max_x // 4 + 1):
        for cell_z in range(min_z // 4, max_z // 4 + 1):
            cx, cz = cell_x >> 2, cell_z >> 2
            key = (cx, cz)
            if key not in chunks:
                chunks[key] = load_chunk_with_cache(config, cx, cz, dimension, regions)
    files = sorted({item[0] for item in chunks.values()})
    backup = begin_write(config, f"set_biome_box {dimension} {biome}", files)
    changed = 0
    for cell_x in range(min_x // 4, max_x // 4 + 1):
        for cell_y in range(min_y // 4, max_y // 4 + 1):
            for cell_z in range(min_z // 4, max_z // 4 + 1):
                cx, cz = cell_x >> 2, cell_z >> 2
                _, _, _, chunk = chunks[(cx, cz)]
                section_y = cell_y >> 2
                section = _section_for_y(chunk, section_y)
                biomes = section.setdefault("biomes", nbtlib.Compound())
                palette = biomes.setdefault("palette", nbtlib.List[nbtlib.String]([nbtlib.String("minecraft:plains")]))
                indices = _decode_biome_indices(biomes)
                palette_index = _biome_palette_index(palette, biome)
                local_index = _biome_local_index(cell_x, cell_y, cell_z)
                if indices[local_index] != palette_index:
                    indices[local_index] = palette_index
                    _encode_biome_indices(biomes, indices)
                    changed += 1
    for _, region, index, chunk in chunks.values():
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in regions.values():
        region.write()
    backup.write_manifest()
    return {"ok": True, "changed_sections": changed, "backup": str(backup.root)}


def _section_for_y(chunk: Any, section_y: int):
    for section in chunk.get("sections", []):
        if int(section.get("Y", 999999)) == section_y:
            return section
    section = nbtlib.Compound({"Y": nbtlib.Byte(section_y)})
    sections = chunk.setdefault("sections", nbtlib.List[nbtlib.Compound]())
    sections.append(section)
    sections.sort(key=lambda item: int(item["Y"]))
    return section


def _biome_bits_for_palette(size: int) -> int:
    return max(1, (size - 1).bit_length())


def _biome_local_index(cell_x: int, cell_y: int, cell_z: int) -> int:
    return ((cell_y & 3) << 4) | ((cell_z & 3) << 2) | (cell_x & 3)


def _biome_palette_index(palette: Any, biome: str) -> int:
    for index, item in enumerate(palette):
        if str(item) == biome:
            return index
    palette.append(nbtlib.String(biome))
    return len(palette) - 1


def _decode_biome_indices(biomes: Any) -> list[int]:
    palette = biomes.get("palette", [])
    data = biomes.get("data")
    if data is None or len(palette) <= 1:
        return [0] * 64
    bits = _biome_bits_for_palette(len(palette))
    values_per_long = 64 // bits
    mask = (1 << bits) - 1
    longs = [int(value) & ((1 << 64) - 1) for value in data]
    result: list[int] = []
    for index in range(64):
        long_index = index // values_per_long
        start = (index % values_per_long) * bits
        result.append((longs[long_index] >> start) & mask if long_index < len(longs) else 0)
    return result


def _encode_biome_indices(biomes: Any, indices: list[int]) -> None:
    palette = biomes["palette"]
    if len(palette) <= 1:
        biomes.pop("data", None)
        return
    bits = _biome_bits_for_palette(len(palette))
    values_per_long = 64 // bits
    long_count = (64 + values_per_long - 1) // values_per_long
    longs = [0] * long_count
    mask = (1 << bits) - 1
    for index, value in enumerate(indices):
        long_index = index // values_per_long
        start = (index % values_per_long) * bits
        longs[long_index] |= (value & mask) << start
    biomes["data"] = nbtlib.LongArray([value - (1 << 64) if value >= (1 << 63) else value for value in longs])


def refresh_heightmaps(config: ServerConfig, chunks: list[dict[str, int]], dimension: str = "overworld", confirm: bool = False) -> dict[str, Any]:
    if len(chunks) > 64 and not confirm:
        raise ValueError("refreshing many heightmaps requires confirm=true")
    regions: dict[Path, RegionFile] = {}
    loaded: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    for item in chunks:
        cx, cz = int(item["cx"]), int(item["cz"])
        loaded[(cx, cz)] = load_chunk_with_cache(config, cx, cz, dimension, regions)
    backup = begin_write(config, f"refresh_heightmaps {dimension}", sorted({item[0] for item in loaded.values()}))
    changed = 0
    for _, region, index, chunk in loaded.values():
        if "Heightmaps" in chunk:
            chunk.pop("Heightmaps", None)
            changed += 1
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in regions.values():
        region.write()
    backup.write_manifest()
    return {"ok": True, "cleared_heightmaps": changed, "backup": str(backup.root)}


def _entity_region_root(config: ServerConfig, dimension: str) -> Path:
    return world_dimension_path(config, dimension) / "entities"


def _poi_region_root(config: ServerConfig, dimension: str) -> Path:
    return world_dimension_path(config, dimension) / "poi"


def _iter_region_chunks(root: Path):
    for path in sorted(root.glob("r.*.*.mca")):
        region = RegionFile(path)
        for index, (_, raw) in region.chunks.items():
            cx_local = index & 31
            cz_local = index >> 5
            match = re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", path.name)
            if not match:
                continue
            cx = int(match.group(1)) * 32 + cx_local
            cz = int(match.group(2)) * 32 + cz_local
            yield path, region, index, cx, cz, parse_chunk_nbt(raw)


def _uuid_string(value: Any) -> str:
    if value is None:
        return ""
    try:
        ints = [int(v) & 0xFFFFFFFF for v in value]
    except Exception:
        return str(value)
    if len(ints) != 4:
        return str(value)
    raw = b"".join(item.to_bytes(4, "big") for item in ints)
    hexed = raw.hex()
    return f"{hexed[:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:]}"


def list_entities(config: ServerConfig, dimension: str = "overworld", entity_id: str = "", max_entities: int = 200) -> list[dict[str, Any]]:
    root = _entity_region_root(config, dimension)
    results: list[dict[str, Any]] = []
    if not root.exists():
        return results
    for path, _, index, cx, cz, chunk in _iter_region_chunks(root):
        for ordinal, entity in enumerate(chunk.get("Entities", [])):
            current_id = str(entity.get("id", ""))
            if entity_id and current_id != entity_id:
                continue
            pos = entity.get("Pos", [])
            results.append({
                "id": current_id,
                "uuid": _uuid_string(entity.get("UUID")),
                "chunk": {"cx": cx, "cz": cz, "index": index},
                "ordinal": ordinal,
                "region": path.relative_to(config.root).as_posix(),
                "pos": [float(v) for v in pos] if len(pos) == 3 else [],
            })
            if len(results) >= max_entities:
                return results
    return results


def edit_entity(config: ServerConfig, uuid: str, nbt_path: str, snbt_value: str, dimension: str = "overworld") -> dict[str, Any]:
    root = _entity_region_root(config, dimension)
    if not root.exists():
        raise FileNotFoundError(root)
    for path, region, index, _, _, chunk in _iter_region_chunks(root):
        for entity in chunk.get("Entities", []):
            if _uuid_string(entity.get("UUID")).lower() == uuid.lower():
                set_at_path(entity, nbt_path, nbtlib.parse_nbt(snbt_value))
                backup = begin_write(config, f"edit_entity {uuid} {nbt_path}", [path])
                region.set_raw(index, write_chunk_nbt(chunk))
                region.write()
                backup.write_manifest()
                return {"ok": True, "uuid": uuid, "backup": str(backup.root)}
    raise FileNotFoundError(f"entity UUID not found: {uuid}")


def add_entity(config: ServerConfig, entity_snbt: str, dimension: str = "overworld") -> dict[str, Any]:
    entity = nbtlib.parse_nbt(entity_snbt)
    if not isinstance(entity, nbtlib.Compound):
        raise ValueError("entity_snbt must be an SNBT compound")
    pos = entity.get("Pos")
    if pos is None or len(pos) != 3:
        raise ValueError("entity_snbt must include Pos as a three-value list")
    x, _, z = float(pos[0]), float(pos[1]), float(pos[2])
    cx, cz = int(x) >> 4, int(z) >> 4
    rx, rz, index = region_coords(cx, cz)
    root = _entity_region_root(config, dimension)
    path = root / f"r.{rx}.{rz}.mca"
    if not path.exists():
        raise FileNotFoundError(f"entity region does not exist: {path}")
    region = RegionFile(path)
    raw = region.get_raw(index)
    if raw is None:
        raise FileNotFoundError(f"entity chunk {cx},{cz} does not exist in {path}")
    chunk = parse_chunk_nbt(raw)
    entities = chunk.setdefault("Entities", nbtlib.List[nbtlib.Compound]())
    entities.append(entity)
    backup = begin_write(config, f"add_entity {dimension} {entity.get('id', '')}", [path])
    region.set_raw(index, write_chunk_nbt(chunk))
    region.write()
    backup.write_manifest()
    return {
        "ok": True,
        "id": str(entity.get("id", "")),
        "chunk": {"cx": cx, "cz": cz},
        "entity_count": len(entities),
        "backup": str(backup.root),
    }


def delete_entities(config: ServerConfig, entity_id: str, dimension: str = "overworld", max_delete: int = 50, confirm: bool = False) -> dict[str, Any]:
    if max_delete > 50 and not confirm:
        raise ValueError("large entity deletion requires confirm=true")
    root = _entity_region_root(config, dimension)
    if not root.exists():
        return {"ok": True, "deleted": 0}
    touched: list[tuple[Path, RegionFile, int, Any]] = []
    deleted = 0
    for path, region, index, _, _, chunk in _iter_region_chunks(root):
        entities = chunk.get("Entities")
        if entities is None:
            continue
        kept = nbtlib.List[nbtlib.Compound]()
        chunk_deleted = 0
        for entity in entities:
            if str(entity.get("id", "")) == entity_id and deleted < max_delete:
                deleted += 1
                chunk_deleted += 1
            else:
                kept.append(entity)
        if chunk_deleted:
            chunk["Entities"] = kept
            touched.append((path, region, index, chunk))
    if not touched:
        return {"ok": True, "deleted": 0}
    backup = begin_write(config, f"delete_entities {entity_id}", sorted({item[0] for item in touched}))
    for _, region, index, chunk in touched:
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in {id(item[1]): item[1] for item in touched}.values():
        region.write()
    backup.write_manifest()
    return {"ok": True, "deleted": deleted, "backup": str(backup.root)}


def _walk_poi_records(node: Any, path: str = ""):
    if isinstance(node, nbtlib.Compound):
        if "type" in node and "pos" in node:
            yield path, node
        for key, value in node.items():
            yield from _walk_poi_records(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, nbtlib.List):
        for index, value in enumerate(node):
            yield from _walk_poi_records(value, f"{path}[{index}]")


def list_poi(config: ServerConfig, dimension: str = "overworld", poi_type: str = "", max_poi: int = 200) -> list[dict[str, Any]]:
    root = _poi_region_root(config, dimension)
    results: list[dict[str, Any]] = []
    if not root.exists():
        return results
    for path, _, index, cx, cz, chunk in _iter_region_chunks(root):
        for record_path, record in _walk_poi_records(chunk):
            current_type = str(record.get("type", ""))
            if poi_type and current_type != poi_type:
                continue
            pos = record.get("pos", [])
            results.append({
                "type": current_type,
                "path": record_path,
                "chunk": {"cx": cx, "cz": cz, "index": index},
                "region": path.relative_to(config.root).as_posix(),
                "pos": [int(v) for v in pos] if len(pos) == 3 else [],
                "free_tickets": int(record.get("free_tickets", 0)),
            })
            if len(results) >= max_poi:
                return results
    return results


def delete_poi(config: ServerConfig, poi_type: str, dimension: str = "overworld", max_delete: int = 100, confirm: bool = False) -> dict[str, Any]:
    if max_delete > 100 and not confirm:
        raise ValueError("large POI deletion requires confirm=true")
    root = _poi_region_root(config, dimension)
    if not root.exists():
        return {"ok": True, "deleted": 0}
    # POI layouts vary; this safely deletes matching records from any list that directly contains record compounds.
    touched: list[tuple[Path, RegionFile, int, Any]] = []
    deleted = 0

    def prune_lists(node: Any) -> int:
        nonlocal deleted
        removed = 0
        if isinstance(node, nbtlib.List):
            kept = []
            for item in node:
                if isinstance(item, nbtlib.Compound) and str(item.get("type", "")) == poi_type and deleted < max_delete:
                    deleted += 1
                    removed += 1
                else:
                    removed += prune_lists(item)
                    kept.append(item)
            if removed:
                node.clear()
                for item in kept:
                    node.append(item)
        elif isinstance(node, nbtlib.Compound):
            for value in node.values():
                removed += prune_lists(value)
        return removed

    for path, region, index, _, _, chunk in _iter_region_chunks(root):
        if prune_lists(chunk):
            touched.append((path, region, index, chunk))
    if not touched:
        return {"ok": True, "deleted": 0}
    backup = begin_write(config, f"delete_poi {poi_type}", sorted({item[0] for item in touched}))
    for _, region, index, chunk in touched:
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in {id(item[1]): item[1] for item in touched}.values():
        region.write()
    backup.write_manifest()
    return {"ok": True, "deleted": deleted, "backup": str(backup.root)}


def prune_chunks(config: ServerConfig, chunks: list[dict[str, int]], dimension: str = "overworld", include_entities: bool = True, include_poi: bool = True, confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("chunk pruning requires confirm=true")
    roots = [world_dimension_path(config, dimension) / "region"]
    if include_entities:
        roots.append(_entity_region_root(config, dimension))
    if include_poi:
        roots.append(_poi_region_root(config, dimension))
    files: set[Path] = set()
    region_cache: dict[Path, RegionFile] = {}
    targets: list[tuple[Path, int]] = []
    for item in chunks:
        cx, cz = int(item["cx"]), int(item["cz"])
        _, _, index = region_coords(cx, cz)
        for root in roots:
            if root.name == "region":
                path = region_path(config, dimension, cx, cz)
            else:
                rx, rz, _ = region_coords(cx, cz)
                path = root / f"r.{rx}.{rz}.mca"
            if path.exists():
                region_cache.setdefault(path, RegionFile(path))
                targets.append((path, index))
                files.add(path)
    backup = begin_write(config, f"prune_chunks {dimension}", sorted(files))
    deleted = 0
    for path, index in targets:
        region = region_cache[path]
        if region.delete_raw(index):
            deleted += 1
    for region in region_cache.values():
        region.write()
    backup.write_manifest()
    return {"ok": True, "deleted_records": deleted, "backup": str(backup.root)}


def analyze_latest_log(config: ServerConfig, max_lines: int = 200) -> dict[str, Any]:
    log = config.root / "logs" / "latest.log"
    if not log.exists():
        return {"exists": False, "issues": []}
    patterns = {
        "errors": re.compile(r"\bERROR\b|Exception|Couldn't parse|Parsing error", re.IGNORECASE),
        "warnings": re.compile(r"\bWARN\b|Cannot|Could not|Failed", re.IGNORECASE),
        "datapack": re.compile(r"datapack|loot_tables|recipe|advancement|tags/functions", re.IGNORECASE),
        "unknown_ids": re.compile(r"unknown (?:string|item|loot table)|Unknown item|Expected name to be an item", re.IGNORECASE),
    }
    buckets = {key: [] for key in patterns}
    resource_pattern = re.compile(
        r"(?:loot_tables?|recipe|advancement|custom advancement|element)\s*:?\s*([a-z0-9_.-]+:[a-z0-9_./-]+)",
        re.IGNORECASE,
    )
    resource_issues: dict[str, list[str]] = {}
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        for key, pattern in patterns.items():
            if pattern.search(line):
                buckets[key].append(line)
        if re.search(r"ERROR|WARN|Couldn't parse|Parsing error|Unknown", line, re.IGNORECASE):
            for match in resource_pattern.finditer(line):
                resource_issues.setdefault(match.group(1), []).append(line)
    return {
        "exists": True,
        "path": log.relative_to(config.root).as_posix(),
        "world": config.world_name,
        "support": detect_world_info(config).as_dict(),
        "issues": {key: value[-max_lines:] for key, value in buckets.items()},
        "resource_issues": {key: value[-max_lines:] for key, value in sorted(resource_issues.items())},
    }
