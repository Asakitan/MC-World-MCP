from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import nbtlib
from PIL import Image

from .anvil import block_state_to_string, decode_indices, load_chunk_with_cache, local_index, RegionFile
from .config import ServerConfig
from .paths import resolve_under_root
from .templates import _palette_entry_to_string

AIR_BLOCKS = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
WATER_BLOCKS = {"minecraft:water"}
SURFACE_MODES = {"surface", "top", "heightmap"}
OCEAN_FLOOR_MODES = {"ocean_floor", "oceanfloor", "seafloor", "sea_floor", "floor"}

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
) -> dict[str, Any]:
    y_mode = _normalize_y_mode(y_mode)
    min_x, max_x = sorted((x1, x2))
    min_z, max_z = sorted((z1, z2))
    width = max_x - min_x + 1
    height = max_z - min_z + 1
    _check_preview_size(width * height)
    image = Image.new("RGB", (width, height), BLOCK_COLORS["minecraft:air"])
    counts: dict[str, int] = {}
    chunk_cache = _ChunkReadCache()
    pixels: list[tuple[int, int, int]] = []
    for z in range(min_z, max_z + 1):
        for x in range(min_x, max_x + 1):
            block = _surface_block(config, x, z, y_mode, dimension, chunk_cache)
            counts[block] = counts.get(block, 0) + 1
            pixels.append(color_for_block(block))
    image.putdata(pixels)
    path = _preview_path(config, "map")
    _save_preview(image, path)
    return {
        "ok": True,
        "path": str(path),
        "dimension": dimension,
        "bounds": {"x1": min_x, "z1": min_z, "x2": max_x, "z2": max_z, "y_mode": y_mode},
        "size": {"width": width, "height": height},
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
    pixels: list[tuple[int, int, int]] = []
    for y in range(max_y, min_y - 1, -1):
        for a in range(min_a, max_a + 1):
            x, z = (fixed, a) if axis == "x" else (a, fixed)
            block = _get_block_cached(config, x, y, z, dimension, chunk_cache)
            counts[block] = counts.get(block, 0) + 1
            pixels.append(color_for_block(block))
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
    counts: dict[str, int] = {}
    seen: dict[tuple[int, int], tuple[int, str]] = {}
    for block in template.get("blocks", []):
        pos = [int(v) for v in block.get("pos", [0, 0, 0])]
        state = int(block.get("state", 0))
        block_id = _palette_entry_to_string(palette[state]) if state < len(palette) else "minecraft:air"
        px, py, pz = pos
        if axis == "y":
            key, depth = (px, pz), py
        elif axis == "x":
            key, depth = (pz, size[1] - py - 1), px
        else:
            key, depth = (px, size[1] - py - 1), pz
        current = seen.get(key)
        if current is None or depth >= current[0]:
            seen[key] = (depth, block_id)
    for (px, py), (_, block_id) in seen.items():
        if 0 <= px < image.width and 0 <= py < image.height:
            counts[block_id] = counts.get(block_id, 0) + 1
            image.putpixel((px, py), color_for_block(block_id))
    path = _preview_path(config, "template")
    _save_preview(image, path)
    return {
        "ok": True,
        "path": str(path),
        "template": template_path,
        "axis": axis,
        "size": {"width": image.width, "height": image.height, "template": size},
        "blocks_projected": len(seen),
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
            self._indices = decode_indices(self.block_states)
        return self._indices

    def block_at(self, x: int, y: int, z: int) -> str:
        if len(self.palette) == 1:
            return self.palette[0]
        index = self.indices[local_index(x, y, z)]
        return self.palette[index] if index < len(self.palette) else "minecraft:air"

    def top_block_matching(self, x: int, z: int, skip: set[str]) -> str | None:
        if len(self.palette) == 1:
            block = self.palette[0]
            return None if self.palette_base_names[0] in skip else block
        if all(block in skip for block in self.palette_base_names):
            return None
        lx = x & 15
        lz = z & 15
        column_offset = (lz << 4) | lx
        indices = self.indices
        for ly in range(15, -1, -1):
            index = indices[(ly << 8) | column_offset]
            block = self.palette[index] if index < len(self.palette) else "minecraft:air"
            if block.split("[", 1)[0] not in skip:
                return block
        return None


@dataclass
class _PreparedChunk:
    sections_desc: list[_PreparedSection]
    sections_by_y: dict[int, _PreparedSection]

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

    def top_block_matching(self, x: int, z: int, skip: set[str]) -> str:
        for section in self.sections_desc:
            block = section.top_block_matching(x, z, skip)
            if block is not None:
                return block
        return "minecraft:air"


class _ChunkReadCache:
    def __init__(self) -> None:
        self.regions: dict[Path, RegionFile] = {}
        self.chunks: dict[tuple[int, int], _PreparedChunk | None] = {}

    def get(self, config: ServerConfig, cx: int, cz: int, dimension: str) -> _PreparedChunk | None:
        key = (cx, cz)
        if key not in self.chunks:
            try:
                chunk = load_chunk_with_cache(config, cx, cz, dimension, self.regions)[3]
            except FileNotFoundError:
                self.chunks[key] = None
            else:
                self.chunks[key] = _PreparedChunk.from_chunk(chunk)
        return self.chunks[key]


def _surface_block(config: ServerConfig, x: int, z: int, y_mode: str, dimension: str, chunk_cache: _ChunkReadCache) -> str:
    if y_mode.isdecimal() or (y_mode.startswith("-") and y_mode[1:].isdecimal()):
        return _get_block_cached(config, x, int(y_mode), z, dimension, chunk_cache)
    cx, cz = x >> 4, z >> 4
    chunk = chunk_cache.get(config, cx, cz, dimension)
    if chunk is None:
        return "minecraft:air"
    if y_mode in OCEAN_FLOOR_MODES:
        return chunk.top_block_matching(x, z, skip=AIR_BLOCKS | WATER_BLOCKS)
    if y_mode not in SURFACE_MODES:
        raise ValueError(
            "y_mode must be 'surface', 'top', 'ocean_floor', 'seafloor', or an integer Y level"
        )
    return chunk.top_block_matching(x, z, skip=AIR_BLOCKS)


def _normalize_y_mode(y_mode: str) -> str:
    mode = str(y_mode).strip().lower().replace("-", "_")
    if mode == "":
        return "surface"
    return mode


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


def _check_preview_size(pixels: int) -> None:
    if pixels > 262144:
        raise ValueError("preview is too large; keep it at or below 262144 pixels")


def _top_counts(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {"block": block, "count": count}
        for block, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]
