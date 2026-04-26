from __future__ import annotations

import hashlib
import gzip
import struct
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import nbtlib
from PIL import Image

from .anvil import block_state_to_string, decode_indices, local_index, region_coords, region_path
from .config import ServerConfig
from .nbt_io import parse_chunk_nbt
from .paths import resolve_under_root
from .templates import _palette_entry_to_string

try:
    from . import _preview_accel as _PREVIEW_ACCEL
except Exception:
    _PREVIEW_ACCEL = None

AIR_BLOCKS = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
WATER_BLOCKS = {"minecraft:water"}
SURFACE_MODES = {"surface", "top", "heightmap"}
OCEAN_FLOOR_MODES = {"ocean_floor", "oceanfloor", "seafloor", "sea_floor", "floor"}
MAX_PREVIEW_PIXELS = 1_048_576

BLOCK_COLORS = {
    "minecraft:air": (0, 0, 0),
    "minecraft:water": (48, 92, 186),
    "minecraft:stone": (126, 126, 126),
    "minecraft:deepslate": (74, 74, 78),
    "minecraft:dirt": (116, 80, 48),
    "minecraft:grass_block": (92, 142, 62),
    "minecraft:sand": (218, 205, 142),
    "minecraft:red_sand": (190, 103, 33),
    "minecraft:gravel": (132, 128, 123),
    "minecraft:clay": (160, 166, 172),
    "minecraft:kelp": (40, 105, 53),
    "minecraft:seagrass": (58, 132, 72),
    "minecraft:coral_block": (219, 96, 114),
    "minecraft:tube_coral_block": (49, 87, 200),
    "minecraft:brain_coral_block": (207, 86, 155),
    "minecraft:bubble_coral_block": (158, 72, 191),
    "minecraft:fire_coral_block": (186, 45, 41),
    "minecraft:horn_coral_block": (218, 191, 64),
    "minecraft:oak_planks": (166, 130, 78),
    "minecraft:chest": (144, 95, 38),
    "minecraft:glass": (175, 215, 225),
    "minecraft:ice": (143, 184, 245),
    "minecraft:packed_ice": (113, 157, 231),
    "minecraft:snow_block": (236, 248, 248),
    "minecraft:lava": (220, 82, 24),
    "minecraft:bedrock": (50, 50, 50),
    "minecraft:netherrack": (105, 42, 42),
    "minecraft:end_stone": (218, 224, 163),
    "minecraft:tuff": (108, 112, 105),
    "minecraft:calcite": (221, 222, 214),
}


def render_map_preview(
    config: ServerConfig,
    x1: int,
    z1: int,
    x2: int,
    z2: int,
    y_mode: str = "surface",
    dimension: str = "overworld",
    sample: int = 1,
) -> dict[str, Any]:
    y_mode = _normalize_y_mode(y_mode)
    sample = _normalize_sample(sample)
    min_x, max_x = sorted((x1, x2))
    min_z, max_z = sorted((z1, z2))
    sample_xs = range(min_x, max_x + 1, sample)
    sample_zs = range(min_z, max_z + 1, sample)
    width = len(sample_xs)
    height = len(sample_zs)
    _check_preview_size(width * height)
    image = Image.new("RGB", (width, height), BLOCK_COLORS["minecraft:air"])
    chunk_cache = _ChunkReadCache()
    if _is_integer_y_mode(y_mode):
        if sample == 1:
            pixels, counts = _render_fixed_y_map(config, min_x, max_x, min_z, max_z, int(y_mode), dimension, chunk_cache)
        else:
            pixels, counts = _render_sampled_fixed_y_map(config, sample_xs, sample_zs, int(y_mode), dimension, chunk_cache)
    else:
        if y_mode in OCEAN_FLOOR_MODES:
            if sample == 1:
                pixels, counts = _render_top_map(config, min_x, max_x, min_z, max_z, AIR_BLOCKS | WATER_BLOCKS, dimension, chunk_cache)
            else:
                pixels, counts = _render_sampled_top_map(config, sample_xs, sample_zs, AIR_BLOCKS | WATER_BLOCKS, dimension, chunk_cache)
        elif y_mode in SURFACE_MODES:
            if sample == 1:
                pixels, counts = _render_top_map(config, min_x, max_x, min_z, max_z, AIR_BLOCKS, dimension, chunk_cache)
            else:
                pixels, counts = _render_sampled_top_map(config, sample_xs, sample_zs, AIR_BLOCKS, dimension, chunk_cache)
        else:
            raise ValueError(
                "y_mode must be 'surface', 'top', 'ocean_floor', 'seafloor', or an integer Y level"
            )
    image.putdata(pixels)
    path = _preview_path(config, "map")
    _save_preview(image, path)
    return {
        "ok": True,
        "path": str(path),
        "dimension": dimension,
        "bounds": {"x1": min_x, "z1": min_z, "x2": max_x, "z2": max_z, "y_mode": y_mode, "sample": sample},
        "size": {"width": width, "height": height, "sample": sample},
        "top_blocks": _top_counts(counts),
    }


def render_slice_preview(
    config: ServerConfig,
    axis: str,
    fixed: int,
    min_a: int,
    max_a: int,
    min_y: int,
    max_y: int,
    dimension: str = "overworld",
) -> dict[str, Any]:
    axis = axis.lower()
    if axis not in {"x", "z"}:
        raise ValueError("axis must be 'x' or 'z'")
    min_a, max_a = sorted((min_a, max_a))
    min_y, max_y = sorted((min_y, max_y))
    width = max_a - min_a + 1
    height = max_y - min_y + 1
    _check_preview_size(width * height)
    image = Image.new("RGB", (width, height), BLOCK_COLORS["minecraft:air"])
    counts: dict[str, int] = {}
    chunk_cache = _ChunkReadCache()
    color_cache: dict[str, tuple[int, int, int]] = {}
    pixels: list[tuple[int, int, int]] = []
    for y in range(max_y, min_y - 1, -1):
        for a in range(min_a, max_a + 1):
            x, z = (fixed, a) if axis == "x" else (a, fixed)
            block = _get_block_cached(config, x, y, z, dimension, chunk_cache)
            counts[block] = counts.get(block, 0) + 1
            pixels.append(_cached_color(block, color_cache))
    image.putdata(pixels)
    path = _preview_path(config, "slice")
    _save_preview(image, path)
    return {
        "ok": True,
        "path": str(path),
        "dimension": dimension,
        "axis": axis,
        "fixed": fixed,
        "bounds": {"min_a": min_a, "max_a": max_a, "min_y": min_y, "max_y": max_y},
        "size": {"width": width, "height": height},
        "top_blocks": _top_counts(counts),
    }


def render_template_preview(config: ServerConfig, template_path: str, axis: str = "y") -> dict[str, Any]:
    axis = axis.lower()
    if axis not in {"x", "y", "z"}:
        raise ValueError("axis must be 'x', 'y', or 'z'")
    target = resolve_under_root(config, template_path)
    template = nbtlib.load(target)
    size = [int(v) for v in template.get("size", [1, 1, 1])]
    palette = template.get("palette", [])
    if axis == "y":
        width, height = size[0], size[2]
    elif axis == "x":
        width, height = size[2], size[1]
    else:
        width, height = size[0], size[1]
    _check_preview_size(width * height)
    image = Image.new("RGB", (max(width, 1), max(height, 1)), BLOCK_COLORS["minecraft:air"])
    palette_blocks = [_palette_entry_to_string(entry) for entry in palette]
    palette_colors = [color_for_block(block) for block in palette_blocks]
    pixel_count = image.width * image.height
    if _PREVIEW_ACCEL is not None:
        states = _PREVIEW_ACCEL.project_template_states(
            template.get("blocks", []),
            image.width,
            image.height,
            size[1],
            {"y": 0, "x": 1, "z": 2}[axis],
        )
    else:
        depths = [-1] * pixel_count
        states = [-1] * pixel_count
        for block in template.get("blocks", []):
            pos = block.get("pos", [0, 0, 0])
            px, py, pz = int(pos[0]), int(pos[1]), int(pos[2])
            state = int(block.get("state", 0))
            if axis == "y":
                image_x, image_y, depth = px, pz, py
            elif axis == "x":
                image_x, image_y, depth = pz, size[1] - py - 1, px
            else:
                image_x, image_y, depth = px, size[1] - py - 1, pz
            if 0 <= image_x < image.width and 0 <= image_y < image.height:
                index = image_y * image.width + image_x
                if depth >= depths[index]:
                    depths[index] = depth
                    states[index] = state

    pixels = [BLOCK_COLORS["minecraft:air"]] * pixel_count
    counts: dict[str, int] = {}
    blocks_projected = 0
    for index, state in enumerate(states):
        if state >= 0:
            block_id = palette_blocks[state] if state < len(palette_blocks) else "minecraft:air"
            counts[block_id] = counts.get(block_id, 0) + 1
            pixels[index] = palette_colors[state] if state < len(palette_colors) else BLOCK_COLORS["minecraft:air"]
            blocks_projected += 1
    image.putdata(pixels)
    path = _preview_path(config, "template")
    _save_preview(image, path)
    return {
        "ok": True,
        "path": str(path),
        "template": template_path,
        "axis": axis,
        "size": {"width": image.width, "height": image.height, "template": size},
        "blocks_projected": blocks_projected,
        "top_blocks": _top_counts(counts),
    }


def color_for_block(block: str) -> tuple[int, int, int]:
    name = block.split("[", 1)[0]
    if name in BLOCK_COLORS:
        return BLOCK_COLORS[name]
    if name.endswith("_leaves"):
        return (75, 135, 67)
    if name.endswith("_log") or name.endswith("_wood"):
        return (112, 78, 44)
    if "coral" in name:
        return (205, 91, 130)
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return (64 + digest[0] % 160, 64 + digest[1] % 160, 64 + digest[2] % 160)


@dataclass
class _PreparedSection:
    y: int
    block_states: Any
    palette: list[str]
    palette_base_names: list[str]
    _indices: list[int] | None = field(default=None, init=False, repr=False)

    @classmethod
    def from_section(cls, section: Any) -> "_PreparedSection | None":
        block_states = section.get("block_states")
        if not block_states:
            return None
        palette = [block_state_to_string(entry) for entry in block_states.get("palette", [])]
        if not palette:
            palette = ["minecraft:air"]
        return cls(
            y=int(section.get("Y", 0)),
            block_states=block_states,
            palette=palette,
            palette_base_names=[block.split("[", 1)[0] for block in palette],
        )

    @property
    def indices(self) -> list[int]:
        if self._indices is None:
            self._indices = _decode_indices(self.block_states)
        return self._indices

    def block_at(self, x: int, y: int, z: int) -> str:
        if len(self.palette) == 1:
            return self.palette[0]
        index = self.indices[local_index(x, y, z)]
        return self.palette[index] if index < len(self.palette) else "minecraft:air"

    def fill_top_projection(self, unresolved: list[int], blocks: list[str], skip: set[str]) -> list[int]:
        if len(self.palette) == 1:
            if self.palette_base_names[0] in skip:
                return unresolved
            block = self.palette[0]
            for column in unresolved:
                blocks[column] = block
            return []
        if all(block in skip for block in self.palette_base_names):
            return unresolved
        if _PREVIEW_ACCEL is not None:
            return _PREVIEW_ACCEL.fill_top_projection(
                self.indices,
                self.palette,
                self.palette_base_names,
                skip,
                unresolved,
                blocks,
            )

        indices = self.indices
        remaining = unresolved
        for ly in range(15, -1, -1):
            y_offset = ly << 8
            next_remaining: list[int] = []
            for column in remaining:
                index = indices[y_offset | column]
                block = self.palette[index] if index < len(self.palette) else "minecraft:air"
                if block.split("[", 1)[0] in skip:
                    next_remaining.append(column)
                else:
                    blocks[column] = block
            remaining = next_remaining
            if not remaining:
                break
        return remaining


@dataclass
class _PreparedChunk:
    sections_desc: list[_PreparedSection]
    sections_by_y: dict[int, _PreparedSection]
    _top_blocks_cache: dict[frozenset[str], list[str]] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def from_chunk(cls, chunk: Any) -> "_PreparedChunk":
        sections: list[_PreparedSection] = []
        for section in chunk.get("sections", []):
            prepared = _PreparedSection.from_section(section)
            if prepared is not None:
                sections.append(prepared)
        sections.sort(key=lambda section: section.y, reverse=True)
        return cls(sections, {section.y: section for section in sections})

    def block_at(self, x: int, y: int, z: int) -> str:
        section = self.sections_by_y.get(y // 16)
        return section.block_at(x, y, z) if section is not None else "minecraft:air"

    def top_blocks(self, skip: set[str]) -> list[str]:
        key = frozenset(skip)
        cached = self._top_blocks_cache.get(key)
        if cached is not None:
            return cached
        blocks = ["minecraft:air"] * 256
        unresolved = list(range(256))
        for section in self.sections_desc:
            unresolved = section.fill_top_projection(unresolved, blocks, skip)
            if not unresolved:
                break
        self._top_blocks_cache[key] = blocks
        return blocks


class _LazyRegion:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.locations: list[tuple[int, int]] = [(0, 0)] * 1024
        if path.exists():
            with path.open("rb") as handle:
                header = handle.read(4096)
            if len(header) == 4096:
                self.locations = [
                    (int.from_bytes(header[index * 4:index * 4 + 3], "big"), header[index * 4 + 3])
                    for index in range(1024)
                ]
        self.raw_chunks: dict[int, bytes | None] = {}

    def get_raw(self, index: int) -> bytes | None:
        if index not in self.raw_chunks:
            self.raw_chunks[index] = self._read_raw(index)
        return self.raw_chunks[index]

    def _read_raw(self, index: int) -> bytes | None:
        offset, sectors = self.locations[index]
        if not offset or not sectors:
            return None
        with self.path.open("rb") as handle:
            handle.seek(offset * 4096)
            header = handle.read(5)
            if len(header) < 5:
                return None
            length = struct.unpack(">I", header[:4])[0]
            compression = header[4]
            payload = handle.read(max(length - 1, 0))
        if len(payload) < length - 1:
            return None
        if compression == 2:
            return zlib.decompress(payload)
        if compression == 1:
            return gzip.decompress(payload)
        if compression == 3:
            return payload
        raise ValueError(f"unsupported compression {compression}")


class _ChunkReadCache:
    def __init__(self) -> None:
        self.regions: dict[Path, _LazyRegion] = {}
        self.chunks: dict[tuple[int, int], _PreparedChunk | None] = {}

    def get(self, config: ServerConfig, cx: int, cz: int, dimension: str) -> _PreparedChunk | None:
        key = (cx, cz)
        if key not in self.chunks:
            path = region_path(config, dimension, cx, cz)
            region = self.regions.get(path)
            if region is None:
                region = _LazyRegion(path)
                self.regions[path] = region
            _, _, index = region_coords(cx, cz)
            raw = region.get_raw(index)
            if raw is None:
                self.chunks[key] = None
            else:
                chunk = parse_chunk_nbt(raw)
                self.chunks[key] = _PreparedChunk.from_chunk(chunk)
        return self.chunks[key]


def _normalize_y_mode(y_mode: str) -> str:
    mode = str(y_mode).strip().lower().replace("-", "_")
    if mode == "":
        return "surface"
    return mode


def _is_integer_y_mode(y_mode: str) -> bool:
    return y_mode.isdecimal() or (y_mode.startswith("-") and y_mode[1:].isdecimal())


def _decode_indices(block_states: Any) -> list[int]:
    if _PREVIEW_ACCEL is not None:
        return _PREVIEW_ACCEL.decode_indices(block_states.get("data"), len(block_states["palette"]))
    return decode_indices(block_states)


def _normalize_sample(sample: int) -> int:
    try:
        value = int(sample)
    except (TypeError, ValueError):
        raise ValueError("sample must be a positive integer") from None
    if value < 1:
        raise ValueError("sample must be a positive integer")
    return value


def _render_top_map(
    config: ServerConfig,
    min_x: int,
    max_x: int,
    min_z: int,
    max_z: int,
    skip: set[str],
    dimension: str,
    chunk_cache: _ChunkReadCache,
) -> tuple[list[tuple[int, int, int]], dict[str, int]]:
    width = max_x - min_x + 1
    pixels = [BLOCK_COLORS["minecraft:air"]] * (width * (max_z - min_z + 1))
    counts: dict[str, int] = {}
    color_cache: dict[str, tuple[int, int, int]] = {}
    for cz in range(min_z >> 4, (max_z >> 4) + 1):
        for cx in range(min_x >> 4, (max_x >> 4) + 1):
            chunk_min_x = max(min_x, cx << 4)
            chunk_max_x = min(max_x, (cx << 4) + 15)
            chunk_min_z = max(min_z, cz << 4)
            chunk_max_z = min(max_z, (cz << 4) + 15)
            area = (chunk_max_x - chunk_min_x + 1) * (chunk_max_z - chunk_min_z + 1)
            chunk = chunk_cache.get(config, cx, cz, dimension)
            if chunk is None:
                counts["minecraft:air"] = counts.get("minecraft:air", 0) + area
                continue
            projection = chunk.top_blocks(skip)
            for z in range(chunk_min_z, chunk_max_z + 1):
                row_offset = (z - min_z) * width
                source_offset = (z & 15) << 4
                for x in range(chunk_min_x, chunk_max_x + 1):
                    block = projection[source_offset | (x & 15)]
                    counts[block] = counts.get(block, 0) + 1
                    pixels[row_offset + (x - min_x)] = _cached_color(block, color_cache)
    return pixels, counts


def _render_sampled_top_map(
    config: ServerConfig,
    sample_xs: range,
    sample_zs: range,
    skip: set[str],
    dimension: str,
    chunk_cache: _ChunkReadCache,
) -> tuple[list[tuple[int, int, int]], dict[str, int]]:
    pixels: list[tuple[int, int, int]] = []
    counts: dict[str, int] = {}
    color_cache: dict[str, tuple[int, int, int]] = {}
    for z in sample_zs:
        for x in sample_xs:
            chunk = chunk_cache.get(config, x >> 4, z >> 4, dimension)
            if chunk is None:
                block = "minecraft:air"
            else:
                block = chunk.top_blocks(skip)[((z & 15) << 4) | (x & 15)]
            counts[block] = counts.get(block, 0) + 1
            pixels.append(_cached_color(block, color_cache))
    return pixels, counts


def _render_fixed_y_map(
    config: ServerConfig,
    min_x: int,
    max_x: int,
    min_z: int,
    max_z: int,
    y: int,
    dimension: str,
    chunk_cache: _ChunkReadCache,
) -> tuple[list[tuple[int, int, int]], dict[str, int]]:
    width = max_x - min_x + 1
    pixels = [BLOCK_COLORS["minecraft:air"]] * (width * (max_z - min_z + 1))
    counts: dict[str, int] = {}
    color_cache: dict[str, tuple[int, int, int]] = {}
    section_y = y // 16
    for cz in range(min_z >> 4, (max_z >> 4) + 1):
        for cx in range(min_x >> 4, (max_x >> 4) + 1):
            chunk_min_x = max(min_x, cx << 4)
            chunk_max_x = min(max_x, (cx << 4) + 15)
            chunk_min_z = max(min_z, cz << 4)
            chunk_max_z = min(max_z, (cz << 4) + 15)
            area = (chunk_max_x - chunk_min_x + 1) * (chunk_max_z - chunk_min_z + 1)
            chunk = chunk_cache.get(config, cx, cz, dimension)
            section = chunk.sections_by_y.get(section_y) if chunk is not None else None
            if section is None:
                counts["minecraft:air"] = counts.get("minecraft:air", 0) + area
                continue
            if len(section.palette) == 1:
                block = section.palette[0]
                color = _cached_color(block, color_cache)
                counts[block] = counts.get(block, 0) + area
                for z in range(chunk_min_z, chunk_max_z + 1):
                    row_offset = (z - min_z) * width
                    for x in range(chunk_min_x, chunk_max_x + 1):
                        pixels[row_offset + (x - min_x)] = color
                continue
            for z in range(chunk_min_z, chunk_max_z + 1):
                row_offset = (z - min_z) * width
                for x in range(chunk_min_x, chunk_max_x + 1):
                    block = section.block_at(x, y, z)
                    counts[block] = counts.get(block, 0) + 1
                    pixels[row_offset + (x - min_x)] = _cached_color(block, color_cache)
    return pixels, counts


def _render_sampled_fixed_y_map(
    config: ServerConfig,
    sample_xs: range,
    sample_zs: range,
    y: int,
    dimension: str,
    chunk_cache: _ChunkReadCache,
) -> tuple[list[tuple[int, int, int]], dict[str, int]]:
    pixels: list[tuple[int, int, int]] = []
    counts: dict[str, int] = {}
    color_cache: dict[str, tuple[int, int, int]] = {}
    for z in sample_zs:
        for x in sample_xs:
            block = _get_block_cached(config, x, y, z, dimension, chunk_cache)
            counts[block] = counts.get(block, 0) + 1
            pixels.append(_cached_color(block, color_cache))
    return pixels, counts


def _get_block_cached(config: ServerConfig, x: int, y: int, z: int, dimension: str, chunk_cache: _ChunkReadCache) -> str:
    chunk = chunk_cache.get(config, x >> 4, z >> 4, dimension)
    if chunk is None:
        return "minecraft:air"
    return chunk.block_at(x, y, z)


def _preview_path(config: ServerConfig, prefix: str) -> Path:
    root = config.backup_root / "previews" / datetime.now().strftime("%Y%m%d_%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    index = len(list(root.glob(f"{prefix}_*.png"))) + 1
    return root / f"{prefix}_{index:03d}.png"


def _save_preview(image: Image.Image, path: Path) -> None:
    image.save(path, compress_level=1)


def _cached_color(block: str, color_cache: dict[str, tuple[int, int, int]]) -> tuple[int, int, int]:
    color = color_cache.get(block)
    if color is None:
        color = color_for_block(block)
        color_cache[block] = color
    return color


def _check_preview_size(pixels: int) -> None:
    if pixels > MAX_PREVIEW_PIXELS:
        raise ValueError(f"preview is too large; keep it at or below {MAX_PREVIEW_PIXELS} pixels")


def _top_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"block": block, "count": count}
        for block, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]
