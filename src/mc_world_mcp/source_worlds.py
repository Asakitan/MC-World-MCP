from __future__ import annotations

from pathlib import Path
from typing import Any

from .anvil import RegionFile, region_coords
from .compat import detect_world_info
from .config import ServerConfig
from .paths import world_dimension_path
from .safety import begin_write
from .world_ops import scan_world_coverage

def list_local_worlds(config: ServerConfig) -> list[dict[str, Any]]:
    worlds: list[dict[str, Any]] = []
    for path in sorted(config.root.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or not (path / "level.dat").exists():
            continue
        world_config = ServerConfig(config.root, path.name)
        info = detect_world_info(world_config).as_dict()
        worlds.append({
            "name": path.name,
            "path": path.relative_to(config.root).as_posix(),
            "active": path.resolve() == config.world.resolve(),
            "datapacks": len(list((path / "datapacks").iterdir())) if (path / "datapacks").exists() else 0,
            "dimensions": _dimension_counts(world_config),
            "platform": info["platform"],
            "data_version": info["data_version"],
            "support_level": info["support_level"],
        })
    return worlds


def worldgen_source_plan(config: ServerConfig, source_world_name: str = "") -> dict[str, Any]:
    source_name = source_world_name or f"{config.world_name}_regen_source"
    source_config = _world_config(config, source_name)
    source_exists = source_config.world.exists()
    return {
        "goal": "Use Minecraft/Arclight to execute datapack and mod worldgen, then use this MCP only for offline inspection and chunk transfer.",
        "active_world": config.world_name,
        "recommended_source_world": source_name,
        "source_exists": source_exists,
        "source_path": str(source_config.world),
        "can_execute_worldgen": False,
        "why": "This MCP edits Anvil/NBT/datapack files offline. It does not run Minecraft's chunk generator, jigsaw placement, biome modifiers, or mod worldgen code.",
        "workflow": [
            f"Set server.properties level-name={source_name}, or create that world by your normal server workflow.",
            "Start Arclight/Minecraft with the same datapacks and mods, then generate or pregenerate the needed chunks.",
            "Stop the server completely.",
            "Use compare_world_chunks to confirm which source chunks exist and which target chunks would be overwritten.",
            "Use import_chunks_from_world to copy generated region/entities/poi chunk records into the active target world.",
            "Use render_map_preview, inspect_chunk, list_entities, list_poi, and worldgen_report for offline verification.",
        ],
        "source_summary": _world_summary(source_config) if source_exists else None,
    }


def compare_world_chunks(
    config: ServerConfig,
    source_world_name: str,
    min_cx: int,
    min_cz: int,
    max_cx: int,
    max_cz: int,
    dimension: str = "overworld",
) -> dict[str, Any]:
    source_config = _world_config(config, source_world_name)
    _assert_source_not_target(config, source_config)
    min_cx, max_cx = sorted((min_cx, max_cx))
    min_cz, max_cz = sorted((min_cz, max_cz))
    source_regions: dict[Path, RegionFile] = {}
    target_regions: dict[Path, RegionFile] = {}
    source_present: list[dict[str, int]] = []
    target_present: list[dict[str, int]] = []
    missing_source: list[dict[str, int]] = []
    for cx in range(min_cx, max_cx + 1):
        for cz in range(min_cz, max_cz + 1):
            src_path, src_index = _chunk_region_path(source_config, dimension, "region", cx, cz)
            dst_path, dst_index = _chunk_region_path(config, dimension, "region", cx, cz)
            src_region = source_regions.setdefault(src_path, RegionFile(src_path))
            dst_region = target_regions.setdefault(dst_path, RegionFile(dst_path))
            chunk = {"cx": cx, "cz": cz}
            if src_region.get_raw(src_index) is None:
                missing_source.append(chunk)
            else:
                source_present.append(chunk)
            if dst_region.get_raw(dst_index) is not None:
                target_present.append(chunk)
    total = (max_cx - min_cx + 1) * (max_cz - min_cz + 1)
    return {
        "source_world": source_world_name,
        "target_world": config.world_name,
        "dimension": dimension,
        "requested": {"min_cx": min_cx, "min_cz": min_cz, "max_cx": max_cx, "max_cz": max_cz, "chunks": total},
        "source_present": len(source_present),
        "target_present": len(target_present),
        "missing_source": missing_source[:200],
        "would_import": source_present[:200],
        "truncated_lists": len(missing_source) > 200 or len(source_present) > 200,
    }


def import_chunks_from_world(
    config: ServerConfig,
    source_world_name: str,
    chunks: list[dict[str, int]],
    dimension: str = "overworld",
    include_entities: bool = True,
    include_poi: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    if not confirm:
        raise ValueError("chunk import requires confirm=true")
    if not chunks:
        return {"ok": True, "imported_region_chunks": 0, "imported_entity_chunks": 0, "imported_poi_chunks": 0}
    source_config = _world_config(config, source_world_name)
    _assert_source_not_target(config, source_config)
    _assert_import_supported(source_config)
    roots = ["region"]
    if include_entities:
        roots.append("entities")
    if include_poi:
        roots.append("poi")

    target_files: set[Path] = set()
    imports: list[tuple[str, Path, Path, int, bytes]] = []
    missing: list[dict[str, Any]] = []
    for item in chunks:
        cx, cz = int(item["cx"]), int(item["cz"])
        for root_name in roots:
            src_path, index = _chunk_region_path(source_config, dimension, root_name, cx, cz)
            dst_path, _ = _chunk_region_path(config, dimension, root_name, cx, cz)
            raw = RegionFile(src_path).get_raw(index)
            if raw is None:
                if root_name == "region":
                    missing.append({"cx": cx, "cz": cz, "type": root_name, "source": str(src_path)})
                continue
            target_files.add(dst_path)
            imports.append((root_name, src_path, dst_path, index, raw))

    if missing:
        raise FileNotFoundError(f"source world is missing required terrain chunks: {missing[:20]}")

    backup = begin_write(config, f"import_chunks_from_world {source_world_name} {dimension}", sorted(target_files))
    target_regions: dict[Path, RegionFile] = {}
    counts = {"region": 0, "entities": 0, "poi": 0}
    source_files: set[str] = set()
    for root_name, src_path, dst_path, index, raw in imports:
        target_region = target_regions.setdefault(dst_path, RegionFile(dst_path))
        target_region.set_raw(index, raw)
        counts[root_name] += 1
        source_files.add(src_path.relative_to(config.root).as_posix())
    for region in target_regions.values():
        region.write()
    backup.write_manifest()
    return {
        "ok": True,
        "source_world": source_world_name,
        "target_world": config.world_name,
        "dimension": dimension,
        "requested_chunks": len(chunks),
        "imported_region_chunks": counts["region"],
        "imported_entity_chunks": counts["entities"],
        "imported_poi_chunks": counts["poi"],
        "source_files": sorted(source_files),
        "target_files": sorted(path.relative_to(config.root).as_posix() for path in target_files),
        "backup": str(backup.root),
    }


def _world_config(config: ServerConfig, world_name: str) -> ServerConfig:
    if not world_name or Path(world_name).name != world_name or world_name in (".", ".."):
        raise ValueError("world_name must be a local world directory name under MC_SERVER_ROOT")
    world = (config.root / world_name).resolve()
    world.relative_to(config.root.resolve())
    return ServerConfig(config.root, world_name)


def _assert_source_not_target(config: ServerConfig, source_config: ServerConfig) -> None:
    if source_config.world.resolve() == config.world.resolve():
        raise ValueError("source world must be different from the active target world")
    if not source_config.world.exists():
        raise FileNotFoundError(f"source world does not exist: {source_config.world}")


def _assert_import_supported(source_config: ServerConfig) -> None:
    info = detect_world_info(source_config)
    if info.support_level != "full_1_20_1":
        raise RuntimeError(
            "refusing source chunk import: "
            f"source world {source_config.world_name} has platform={info.platform}, "
            f"data_version={info.data_version}, support_level={info.support_level}. {info.reason}"
        )


def _dimension_counts(config: ServerConfig) -> list[dict[str, Any]]:
    return [
        {
            "dimension": item["dimension"],
            "exists": item["exists"],
            "region_files": item["region_files"],
            "entity_files": item["entity_files"],
            "poi_files": item["poi_files"],
        }
        for item in _list_dimension_roots(config)
    ]


def _list_dimension_roots(config: ServerConfig) -> list[dict[str, Any]]:
    candidates = [
        ("overworld", config.world),
        ("nether", config.world / "DIM-1"),
        ("end", config.world / "DIM1"),
    ]
    return [
        {
            "dimension": name,
            "exists": path.exists(),
            "region_files": len(list((path / "region").glob("*.mca"))) if (path / "region").exists() else 0,
            "entity_files": len(list((path / "entities").glob("*.mca"))) if (path / "entities").exists() else 0,
            "poi_files": len(list((path / "poi").glob("*.mca"))) if (path / "poi").exists() else 0,
        }
        for name, path in candidates
    ]


def _world_summary(config: ServerConfig) -> dict[str, Any]:
    info = detect_world_info(config).as_dict()
    return {
        "world": config.world_name,
        "platform": info["platform"],
        "data_version": info["data_version"],
        "support_level": info["support_level"],
        "coverage": scan_world_coverage(config),
    }


def _chunk_region_path(config: ServerConfig, dimension: str, root_name: str, cx: int, cz: int) -> tuple[Path, int]:
    if root_name not in {"region", "entities", "poi"}:
        raise ValueError("root_name must be region, entities, or poi")
    rx, rz, index = region_coords(cx, cz)
    root = world_dimension_path(config, dimension) / root_name
    return root / f"r.{rx}.{rz}.mca", index
