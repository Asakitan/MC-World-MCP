from __future__ import annotations

import json
import math
import re
import struct
import time
import zlib
from pathlib import Path
from typing import Any, Iterable

import nbtlib

from .config import ServerConfig
from .nbt_io import parse_chunk_nbt, write_chunk_nbt
from .paths import world_dimension_path
from .safety import begin_write

try:
    from . import _preview_accel as _PREVIEW_ACCEL
except Exception:
    _PREVIEW_ACCEL = None

REGION_SIZE = 32
SECTION_SIZE = 16
BLOCK_STATE_RE = re.compile(r"^(?P<name>[a-z0-9_.:-]+)(?:\[(?P<props>.*)\])?$")


class RegionFile:
    def __init__(self, path: Path):
        self.path = path
        self.chunks: dict[int, tuple[int, bytes]] = {}
        self.timestamps: list[int] = [0] * 1024
        if path.exists():
            self._read()

    def _read(self) -> None:
        data = self.path.read_bytes()
        if len(data) < 8192:
            return
        locations = data[:4096]
        self.timestamps = list(struct.unpack(">1024I", data[4096:8192]))
        for index in range(1024):
            entry = locations[index * 4:index * 4 + 4]
            offset = int.from_bytes(entry[:3], "big")
            sectors = entry[3]
            if not offset or not sectors:
                continue
            start = offset * 4096
            if start + 5 > len(data):
                continue
            length = struct.unpack(">I", data[start:start + 4])[0]
            compression = data[start + 4]
            payload = data[start + 5:start + 4 + length]
            if compression == 2:
                raw = zlib.decompress(payload)
            elif compression == 1:
                import gzip
                raw = gzip.decompress(payload)
            elif compression == 3:
                raw = payload
            else:
                raise ValueError(f"unsupported compression {compression}")
            self.chunks[index] = (compression, raw)

    def get_raw(self, index: int) -> bytes | None:
        item = self.chunks.get(index)
        return item[1] if item else None

    def set_raw(self, index: int, raw: bytes) -> None:
        self.chunks[index] = (2, raw)
        self.timestamps[index] = int(time.time())

    def delete_raw(self, index: int) -> bool:
        existed = index in self.chunks
        self.chunks.pop(index, None)
        self.timestamps[index] = 0
        return existed

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        locations = bytearray(4096)
        timestamps = bytearray(struct.pack(">1024I", *self.timestamps))
        sectors = [b"\x00" * 4096, b"\x00" * 4096]
        next_sector = 2
        for index in range(1024):
            item = self.chunks.get(index)
            if item is None:
                continue
            raw = item[1]
            compressed = zlib.compress(raw, level=6)
            body = struct.pack(">I", len(compressed) + 1) + bytes([2]) + compressed
            sector_count = math.ceil(len(body) / 4096)
            locations[index * 4:index * 4 + 4] = next_sector.to_bytes(3, "big") + bytes([sector_count])
            for i in range(sector_count):
                sectors.append(body[i * 4096:(i + 1) * 4096].ljust(4096, b"\x00"))
            next_sector += sector_count
        sectors[0] = bytes(locations)
        sectors[1] = bytes(timestamps)
        self.path.write_bytes(b"".join(sectors))


def region_coords(cx: int, cz: int) -> tuple[int, int, int]:
    rx = cx >> 5
    rz = cz >> 5
    index = (cx & 31) + (cz & 31) * 32
    return rx, rz, index


def region_path(config: ServerConfig, dimension: str, cx: int, cz: int) -> Path:
    rx, rz, _ = region_coords(cx, cz)
    return world_dimension_path(config, dimension) / "region" / f"r.{rx}.{rz}.mca"


def scan_regions(config: ServerConfig, dimension: str = "overworld") -> list[dict[str, Any]]:
    root = world_dimension_path(config, dimension) / "region"
    results: list[dict[str, Any]] = []
    for path in sorted(root.glob("r.*.*.mca")):
        match = re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", path.name)
        if match:
            region = RegionFile(path)
            results.append({
                "path": path.relative_to(config.root).as_posix(),
                "rx": int(match.group(1)),
                "rz": int(match.group(2)),
                "chunks": len(region.chunks),
                "size": path.stat().st_size,
            })
    return results


def load_chunk(config: ServerConfig, cx: int, cz: int, dimension: str = "overworld"):
    path = region_path(config, dimension, cx, cz)
    _, _, index = region_coords(cx, cz)
    region = RegionFile(path)
    raw = region.get_raw(index)
    if raw is None:
        raise FileNotFoundError(f"chunk {cx},{cz} not found in {path}")
    return path, region, index, parse_chunk_nbt(raw)


def load_chunk_with_cache(config: ServerConfig, cx: int, cz: int, dimension: str, regions: dict[Path, RegionFile]):
    path = region_path(config, dimension, cx, cz)
    _, _, index = region_coords(cx, cz)
    region = regions.get(path)
    if region is None:
        region = RegionFile(path)
        regions[path] = region
    raw = region.get_raw(index)
    if raw is None:
        raise FileNotFoundError(f"chunk {cx},{cz} not found in {path}")
    return path, region, index, parse_chunk_nbt(raw)


def inspect_chunk(config: ServerConfig, cx: int, cz: int, dimension: str = "overworld") -> dict[str, Any]:
    path, _, _, chunk = load_chunk(config, cx, cz, dimension)
    sections = chunk.get("sections", [])
    return {
        "region": path.relative_to(config.root).as_posix(),
        "cx": cx,
        "cz": cz,
        "sections": [int(sec["Y"]) for sec in sections if "Y" in sec],
        "block_entities": len(chunk.get("block_entities", [])),
        "status": str(chunk.get("Status", "")),
    }


def section_for_y(chunk, y: int):
    sy = y // SECTION_SIZE
    for section in chunk.get("sections", []):
        if int(section.get("Y", 999999)) == sy:
            return section
    section = nbtlib.Compound({
        "Y": nbtlib.Byte(sy),
        "block_states": nbtlib.Compound({
            "palette": nbtlib.List[nbtlib.Compound]([nbtlib.Compound({"Name": nbtlib.String("minecraft:air")})])
        }),
    })
    sections = chunk.setdefault("sections", nbtlib.List[nbtlib.Compound]())
    sections.append(section)
    sections.sort(key=lambda item: int(item["Y"]))
    return section


def block_state_to_string(entry) -> str:
    name = str(entry.get("Name", "minecraft:air"))
    props = entry.get("Properties")
    if not props:
        return name
    pairs = [f"{key}={props[key]}" for key in sorted(props)]
    return f"{name}[{','.join(pairs)}]"


def parse_block_state(block_state: str) -> nbtlib.Compound:
    match = BLOCK_STATE_RE.fullmatch(block_state.strip())
    if not match:
        raise ValueError(f"invalid block state: {block_state}")
    entry = nbtlib.Compound({"Name": nbtlib.String(match.group("name"))})
    props = match.group("props")
    if props:
        prop_compound = nbtlib.Compound()
        for item in props.split(","):
            if "=" not in item:
                raise ValueError(f"invalid block state property: {item}")
            key, value = item.split("=", 1)
            prop_compound[key.strip()] = nbtlib.String(value.strip())
        entry["Properties"] = prop_compound
    return entry


def palette_index_to_block(section, index: int) -> str:
    palette = section["block_states"]["palette"]
    if index >= len(palette):
        return "minecraft:air"
    return block_state_to_string(palette[index])


def bits_for_palette(size: int) -> int:
    return max(4, (size - 1).bit_length())


def signed_to_unsigned(value: int) -> int:
    return value & ((1 << 64) - 1)


def unsigned_to_signed(value: int) -> int:
    return value - (1 << 64) if value >= (1 << 63) else value


def decode_indices(block_states) -> list[int]:
    if _PREVIEW_ACCEL is not None and hasattr(_PREVIEW_ACCEL, "decode_indices"):
        return _PREVIEW_ACCEL.decode_indices(block_states.get("data"), len(block_states["palette"]))
    palette = block_states["palette"]
    data = block_states.get("data")
    if data is None:
        return [0] * 4096
    bits = bits_for_palette(len(palette))
    values_per_long = 64 // bits
    mask = (1 << bits) - 1
    longs = [signed_to_unsigned(int(v)) for v in data]
    values: list[int] = []
    for i in range(4096):
        long_index = i // values_per_long
        start = (i % values_per_long) * bits
        values.append((longs[long_index] >> start) & mask if long_index < len(longs) else 0)
    return values


def count_palette_indices(block_states) -> list[int]:
    palette = block_states.get("palette", [])
    if _PREVIEW_ACCEL is not None and hasattr(_PREVIEW_ACCEL, "count_palette_indices"):
        return _PREVIEW_ACCEL.count_palette_indices(block_states.get("data"), len(palette))
    data = block_states.get("data")
    if not palette:
        return []
    if data is None:
        counts = [0] * len(palette)
        counts[0] = 4096
        return counts
    counts = [0] * len(palette)
    for index in decode_indices(block_states):
        if index < len(counts):
            counts[index] += 1
    return counts


def encode_indices(block_states, indices: list[int]) -> None:
    palette = block_states["palette"]
    if len(palette) <= 1:
        block_states.pop("data", None)
        return
    bits = bits_for_palette(len(palette))
    values_per_long = 64 // bits
    long_count = math.ceil(4096 / values_per_long)
    longs = [0] * long_count
    mask = (1 << bits) - 1
    for i, value in enumerate(indices):
        long_index = i // values_per_long
        start = (i % values_per_long) * bits
        longs[long_index] |= (value & mask) << start
    block_states["data"] = nbtlib.LongArray([unsigned_to_signed(v) for v in longs])


def local_index(x: int, y: int, z: int) -> int:
    lx = x & 15
    ly = y & 15
    lz = z & 15
    return (ly << 8) | (lz << 4) | lx


def get_block(config: ServerConfig, x: int, y: int, z: int, dimension: str = "overworld") -> str:
    cx = x >> 4
    cz = z >> 4
    _, _, _, chunk = load_chunk(config, cx, cz, dimension)
    section = section_for_y(chunk, y)
    indices = decode_indices(section["block_states"])
    return palette_index_to_block(section, indices[local_index(x, y, z)])


def set_block_in_chunk(chunk, x: int, y: int, z: int, block_id: str) -> str:
    section = section_for_y(chunk, y)
    block_states = section["block_states"]
    palette = block_states["palette"]
    indices = decode_indices(block_states)
    before = palette_index_to_block(section, indices[local_index(x, y, z)])
    target = parse_block_state(block_id)
    target_snbt = target.snbt()
    palette_index = None
    for i, item in enumerate(palette):
        if item.snbt() == target_snbt:
            palette_index = i
            break
    if palette_index is None:
        palette.append(target)
        palette_index = len(palette) - 1
    indices[local_index(x, y, z)] = palette_index
    encode_indices(block_states, indices)
    return before


def set_block(config: ServerConfig, x: int, y: int, z: int, block_id: str, dimension: str = "overworld") -> dict[str, Any]:
    cx = x >> 4
    cz = z >> 4
    path, region, index, chunk = load_chunk(config, cx, cz, dimension)
    backup = begin_write(config, f"set_block {dimension} {x} {y} {z} {block_id}", [path])
    before = set_block_in_chunk(chunk, x, y, z, block_id)
    region.set_raw(index, write_chunk_nbt(chunk))
    region.write()
    backup.write_manifest()
    return {"ok": True, "before": before, "after": block_id, "backup": str(backup.root)}


def set_blocks(config: ServerConfig, blocks: Iterable[tuple[int, int, int, str]], dimension: str = "overworld", reason: str = "set_blocks", confirm: bool = False) -> dict[str, Any]:
    items = list(blocks)
    if len(items) > 4096 and not confirm:
        raise ValueError("large block placement requires confirm=true")
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    for x, _, z, _ in items:
        key = (x >> 4, z >> 4)
        if key not in chunks:
            chunks[key] = load_chunk_with_cache(config, key[0], key[1], dimension, regions)
    files = sorted({item[0] for item in chunks.values()})
    backup = begin_write(config, reason, files)
    changed = 0
    affected_chunks: set[tuple[int, int]] = set()
    for x, y, z, block_state in items:
        _, _, _, chunk = chunks[(x >> 4, z >> 4)]
        before = set_block_in_chunk(chunk, x, y, z, block_state)
        if before != block_state:
            changed += 1
            affected_chunks.add((x >> 4, z >> 4))
    for _, region, index, chunk in chunks.values():
        region.set_raw(index, write_chunk_nbt(chunk))
    for region in regions.values():
        region.write()
    backup.write_manifest()
    return {
        "ok": True,
        "changed": changed,
        "affected_chunks": sorted([{"cx": cx, "cz": cz} for cx, cz in affected_chunks], key=lambda item: (item["cz"], item["cx"])),
        "backup": str(backup.root),
    }


def fill_blocks(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, block_id: str, dimension: str = "overworld", confirm: bool = False) -> dict[str, Any]:
    count = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
    if count > 4096 and not confirm:
        raise ValueError("large fill requires confirm=true")
    return _edit_box(config, x1, y1, z1, x2, y2, z2, dimension, confirm, replacement=block_id)


def replace_blocks(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, old_block: str, new_block: str, dimension: str = "overworld", confirm: bool = False) -> dict[str, Any]:
    count = (abs(x2 - x1) + 1) * (abs(y2 - y1) + 1) * (abs(z2 - z1) + 1)
    if count > 4096 and not confirm:
        raise ValueError("large replace requires confirm=true")
    return _edit_box(config, x1, y1, z1, x2, y2, z2, dimension, confirm, replacement=new_block, old_block=old_block)


def _edit_box(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, dimension: str, confirm: bool, replacement: str, old_block: str | None = None) -> dict[str, Any]:
    xs = range(min(x1, x2), max(x1, x2) + 1)
    ys = range(min(y1, y2), max(y1, y2) + 1)
    zs = range(min(z1, z2), max(z1, z2) + 1)
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    for x in xs:
        for z in zs:
            key = (x >> 4, z >> 4)
            if key not in chunks:
                chunks[key] = load_chunk_with_cache(config, key[0], key[1], dimension, regions)
    files = sorted({item[0] for item in chunks.values()})
    backup = begin_write(config, f"edit_box {dimension} {replacement}", files)
    changed = 0
    for x in xs:
        for y in ys:
            for z in zs:
                _, _, _, chunk = chunks[(x >> 4, z >> 4)]
                if old_block is not None and get_block_from_chunk(chunk, x, y, z) != old_block:
                    continue
                before = set_block_in_chunk(chunk, x, y, z, replacement)
                if before != replacement:
                    changed += 1
    affected_chunks: set[tuple[int, int]] = set()
    for key, (_, region, index, chunk) in chunks.items():
        region.set_raw(index, write_chunk_nbt(chunk))
        affected_chunks.add(key)
    for region in regions.values():
        region.write()
    backup.write_manifest()
    return {
        "ok": True,
        "changed": changed,
        "affected_chunks": sorted([{"cx": cx, "cz": cz} for cx, cz in affected_chunks], key=lambda item: (item["cz"], item["cx"])),
        "backup": str(backup.root),
    }


def get_block_from_chunk(chunk, x: int, y: int, z: int) -> str:
    section = section_for_y(chunk, y)
    indices = decode_indices(section["block_states"])
    return palette_index_to_block(section, indices[local_index(x, y, z)])


def read_block_box(config: ServerConfig, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, dimension: str = "overworld", include_air: bool = False, confirm: bool = False) -> dict[str, Any]:
    xs = range(min(x1, x2), max(x1, x2) + 1)
    ys = range(min(y1, y2), max(y1, y2) + 1)
    zs = range(min(z1, z2), max(z1, z2) + 1)
    count = len(xs) * len(ys) * len(zs)
    if count > 4096 and not confirm:
        raise ValueError("large block box read requires confirm=true")
    regions: dict[Path, RegionFile] = {}
    chunks: dict[tuple[int, int], tuple[Path, RegionFile, int, Any]] = {}
    blocks: list[dict[str, Any]] = []
    for x in xs:
        for z in zs:
            key = (x >> 4, z >> 4)
            if key not in chunks:
                chunks[key] = load_chunk_with_cache(config, key[0], key[1], dimension, regions)
    for x in xs:
        for y in ys:
            for z in zs:
                block = get_block_from_chunk(chunks[(x >> 4, z >> 4)][3], x, y, z)
                if include_air or block != "minecraft:air":
                    blocks.append({"x": x, "y": y, "z": z, "block": block})
    return {"count": count, "returned": len(blocks), "blocks": blocks}


def summarize_chunk_palette(config: ServerConfig, cx: int, cz: int, dimension: str = "overworld") -> dict[str, Any]:
    path, _, _, chunk = load_chunk(config, cx, cz, dimension)
    counts: dict[str, int] = {}
    for section in chunk.get("sections", []):
        block_states = section.get("block_states")
        if not block_states:
            continue
        palette = block_states.get("palette", [])
        for index, count in enumerate(count_palette_indices(block_states)):
            if not count:
                continue
            block = block_state_to_string(palette[index]) if index < len(palette) else "minecraft:air"
            counts[block] = counts.get(block, 0) + count
    return {
        "region": path.relative_to(config.root).as_posix(),
        "cx": cx,
        "cz": cz,
        "palette_counts": dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))),
    }
