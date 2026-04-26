from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from . import __version__
from .anvil import fill_blocks as anvil_fill_blocks
from .anvil import get_block as anvil_get_block
from .anvil import inspect_chunk as anvil_inspect_chunk
from .anvil import replace_blocks as anvil_replace_blocks
from .anvil import read_block_box as anvil_read_block_box
from .anvil import scan_regions as anvil_scan_regions
from .anvil import set_block as anvil_set_block
from .anvil import summarize_chunk_palette as anvil_summarize_chunk_palette
from .assistant_guidance import SERVER_INSTRUCTIONS, assistant_instruction_markdown, assistant_instruction_payload
from .compat import detect_world_info, with_support
from .config import load_config
from .datapacks import list_datapacks as dp_list_datapacks
from .datapacks import read_datapack_file as dp_read_datapack_file
from .datapacks import search_datapack_files as dp_search_datapack_files
from .datapacks import validate_datapacks as dp_validate_datapacks
from .datapacks import write_datapack_file as dp_write_datapack_file
from .nbt_io import list_nbt_files as nbt_list_nbt_files
from .nbt_io import read_nbt_file as nbt_read_nbt_file
from .nbt_io import write_nbt_value as nbt_write_nbt_value
from .paths import resolve_under_root
from .preview import render_map_preview as preview_render_map_preview
from .preview import render_slice_preview as preview_render_slice_preview
from .preview import render_template_preview as preview_render_template_preview
from .safety import assert_offline, begin_write, java_processes
from .source_worlds import compare_world_chunks as source_compare_world_chunks
from .source_worlds import import_chunks_from_world as source_import_chunks_from_world
from .source_worlds import list_local_worlds as source_list_local_worlds
from .source_worlds import worldgen_source_plan as source_worldgen_source_plan
from .templates import export_region_to_template as tmpl_export_region_to_template
from .templates import list_structure_templates as tmpl_list_structure_templates
from .templates import place_template_to_region as tmpl_place_template_to_region
from .templates import read_structure_template as tmpl_read_structure_template
from .templates import write_structure_template as tmpl_write_structure_template
from .templates import write_structure_template_value as tmpl_write_structure_template_value
from .world_ops import analyze_latest_log as world_analyze_latest_log
from .world_ops import add_block_entity as world_add_block_entity
from .world_ops import add_entity as world_add_entity
from .world_ops import delete_entities as world_delete_entities
from .world_ops import delete_poi as world_delete_poi
from .world_ops import edit_block_entity as world_edit_block_entity
from .world_ops import edit_entity as world_edit_entity
from .world_ops import list_dimensions as world_list_dimensions
from .world_ops import list_entities as world_list_entities
from .world_ops import list_poi as world_list_poi
from .world_ops import prune_chunks as world_prune_chunks
from .world_ops import refresh_heightmaps as world_refresh_heightmaps
from .world_ops import scan_world_coverage as world_scan_world_coverage
from .world_ops import set_biome_box as world_set_biome_box
from .world_ops import write_chunk_nbt_value as world_write_chunk_nbt_value
from .worldgen import list_worldgen_resources as wg_list_worldgen_resources
from .worldgen import validate_worldgen_references as wg_validate_worldgen_references
from .worldgen import worldgen_report as wg_worldgen_report


CONFIG = load_config()

mcp = FastMCP(
    "mc-world",
    instructions=SERVER_INSTRUCTIONS,
)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def server_properties() -> dict[str, str]:
    return CONFIG.server_properties


def java_safety_summary() -> dict[str, Any]:
    all_processes = java_processes(CONFIG, include_clients=True)
    blocking = [proc for proc in all_processes if proc.get("classification") != "minecraft_client"]
    ignored_clients = [proc for proc in all_processes if proc.get("classification") == "minecraft_client"]
    return {
        "blocking_java_processes": blocking,
        "ignored_client_java_processes": ignored_clients,
    }


@mcp.tool()
def assistant_instructions() -> str:
    """Read this first: return mc-world MCP tool order, safety rules, and source-world workflow guidance."""
    return dumps(assistant_instruction_payload())


@mcp.resource(
    "mc-world://assistant-instructions",
    name="mc-world assistant instructions",
    description="Read this first for mc-world MCP tool order, safety rules, preview modes, and source-world workflow.",
    mime_type="text/markdown",
)
def assistant_instructions_resource() -> str:
    return assistant_instruction_markdown()


@mcp.prompt(
    name="mc_world_assistant_instructions",
    description="Prompt instructions for assistants using the mc-world MCP server.",
)
def assistant_instructions_prompt() -> str:
    return assistant_instruction_markdown()


@mcp.tool()
def server_summary() -> str:
    """Return a local summary of the configured Minecraft server root."""
    props = server_properties()
    world = CONFIG.root / props.get("level-name", "world")
    info = detect_world_info(CONFIG).as_dict()
    java_summary = java_safety_summary()
    return dumps({
        "version": __version__,
        **info,
        "server_root": str(CONFIG.root),
        "configured_level_name": props.get("level-name"),
        "active_world_name": CONFIG.world_name,
        "default_world_path": str(CONFIG.root / "world"),
        "active_world_path": str(CONFIG.world),
        "server_properties_world_path": str(world),
        "world_exists": CONFIG.world.exists(),
        "server_properties_world_exists": world.exists(),
        "datapacks": len(list((CONFIG.world / "datapacks").iterdir())) if (CONFIG.world / "datapacks").exists() else 0,
        "logs_latest_exists": (CONFIG.root / "logs" / "latest.log").exists(),
        **java_summary,
        "java_processes": java_summary["blocking_java_processes"],
    })


@mcp.tool()
def check_offline_safety() -> str:
    """Check whether write tools are allowed to run now."""
    try:
        assert_offline(CONFIG)
        ok = True
        error = ""
    except Exception as exc:
        ok = False
        error = str(exc)
    java_summary = java_safety_summary()
    return dumps(with_support(CONFIG, {
        "ok": ok,
        "error": error,
        "world": str(CONFIG.world),
        **java_summary,
        "java_processes": java_summary["blocking_java_processes"],
    }))


@mcp.tool()
def detect_world_version() -> str:
    """Detect the selected world's platform, DataVersion, and write support level."""
    return dumps(detect_world_info(CONFIG).as_dict())


@mcp.tool()
def world_summary() -> str:
    """Return a world-focused summary for the selected level-name world."""
    datapacks = CONFIG.world / "datapacks"
    return dumps(with_support(CONFIG, {
        "server_root": str(CONFIG.root),
        "world_name": CONFIG.world_name,
        "world_exists": CONFIG.world.exists(),
        "datapacks": len(list(datapacks.iterdir())) if datapacks.exists() else 0,
        "dimensions": world_list_dimensions(CONFIG),
    }))


@mcp.tool()
def list_local_worlds() -> str:
    """List Java worlds under the server root, including source/target candidates."""
    return dumps(source_list_local_worlds(CONFIG))


@mcp.tool()
def worldgen_source_plan(source_world_name: str = "") -> str:
    """Describe the safe workflow for server-generated source worlds and offline import."""
    return dumps(source_worldgen_source_plan(CONFIG, source_world_name))


@mcp.tool()
def compare_world_chunks(source_world_name: str, min_cx: int, min_cz: int, max_cx: int, max_cz: int, dimension: str = "overworld") -> str:
    """Compare generated chunk coverage between a source world and the active target world."""
    return dumps(source_compare_world_chunks(CONFIG, source_world_name, min_cx, min_cz, max_cx, max_cz, dimension))


@mcp.tool()
def import_chunks_from_world(source_world_name: str, chunks: list[dict[str, int]], dimension: str = "overworld", include_entities: bool = True, include_poi: bool = True, confirm: bool = False) -> str:
    """Import already-generated terrain/entities/POI chunks from a local source world into the active world."""
    return dumps(with_support(CONFIG, source_import_chunks_from_world(CONFIG, source_world_name, chunks, dimension, include_entities, include_poi, confirm)))


@mcp.tool()
def list_dimensions() -> str:
    """List standard Java dimensions and available region/entity/POI files."""
    return dumps(with_support(CONFIG, world_list_dimensions(CONFIG)))


@mcp.tool()
def scan_world_coverage(dimension: str = "overworld") -> str:
    """Summarize region and chunk coverage for a dimension."""
    return dumps(with_support(CONFIG, world_scan_world_coverage(CONFIG, dimension)))


@mcp.tool()
def analyze_latest_log(max_lines: int = 200) -> str:
    """Group important startup/runtime log warnings and errors."""
    return dumps(world_analyze_latest_log(CONFIG, max_lines))


@mcp.tool()
def list_server_files(relative_path: str = ".", max_entries: int = 200) -> str:
    """List safe server files below an allowlisted path."""
    base = CONFIG.root if relative_path == "." else resolve_under_root(CONFIG, relative_path)
    entries = []
    for path in sorted(base.iterdir(), key=lambda p: p.name.lower())[:max_entries]:
        entries.append({
            "name": path.name,
            "path": path.relative_to(CONFIG.root).as_posix(),
            "type": "dir" if path.is_dir() else "file",
            "size": path.stat().st_size if path.is_file() else None,
        })
    return dumps(entries)


@mcp.tool()
def read_server_file(relative_path: str, max_chars: int = 20000) -> str:
    """Read a text file from a safe server path."""
    target = resolve_under_root(CONFIG, relative_path)
    text = target.read_text(encoding="utf-8", errors="replace")
    return text[:max_chars]


@mcp.tool()
def write_server_file(relative_path: str, content: str) -> str:
    """Write a text file under a safe server path after offline checks and backup."""
    target = resolve_under_root(CONFIG, relative_path, write=True)
    backup = begin_write(CONFIG, f"write_server_file {relative_path}", [target])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")
    backup.write_manifest()
    return dumps({"ok": True, "backup": str(backup.root)})


@mcp.tool()
def read_server_log(lines: int = 100) -> str:
    """Read the last N lines from logs/latest.log."""
    target = CONFIG.root / "logs" / "latest.log"
    if not target.exists():
        return "ERROR: logs/latest.log not found"
    data = target.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-lines:])


@mcp.tool()
def grep_server_log(pattern: str, max_lines: int = 50) -> str:
    """Search logs/latest.log offline."""
    target = CONFIG.root / "logs" / "latest.log"
    if not target.exists():
        return "ERROR: logs/latest.log not found"
    matches = [line for line in target.read_text(encoding="utf-8", errors="replace").splitlines() if pattern.lower() in line.lower()]
    return "\n".join(matches[-max_lines:])


@mcp.tool()
def read_level_dat(path: str = "", max_depth: int = 5) -> str:
    """Read world/level.dat, optionally at a dotted NBT path."""
    return nbt_read_nbt_file(CONFIG, f"{CONFIG.world_name}/level.dat", path, max_depth)


@mcp.tool()
def write_level_dat_value(path: str, snbt_value: str) -> str:
    """Write one SNBT value into world/level.dat."""
    return nbt_write_nbt_value(CONFIG, f"{CONFIG.world_name}/level.dat", path, snbt_value)


@mcp.tool()
def list_nbt_files() -> str:
    """List known NBT files in the world."""
    return dumps(nbt_list_nbt_files(CONFIG))


@mcp.tool()
def read_nbt_file(relative_path: str, path: str = "", max_depth: int = 5) -> str:
    """Read an NBT file from an allowlisted path."""
    return nbt_read_nbt_file(CONFIG, relative_path, path, max_depth)


@mcp.tool()
def write_nbt_value(relative_path: str, path: str, snbt_value: str) -> str:
    """Write one SNBT value into an NBT file."""
    return nbt_write_nbt_value(CONFIG, relative_path, path, snbt_value)


@mcp.tool()
def list_datapacks() -> str:
    """List installed folder and zip datapacks."""
    return dumps(with_support(CONFIG, dp_list_datapacks(CONFIG)))


@mcp.tool()
def validate_datapacks() -> str:
    """Validate datapack JSON and unexpected duplicate resources."""
    return dumps(with_support(CONFIG, dp_validate_datapacks(CONFIG)))


@mcp.tool()
def list_worldgen_resources(namespace: str = "", type: str = "") -> str:
    """List datapack worldgen resources, structures, biome modifiers, and tags."""
    return dumps(with_support(CONFIG, wg_list_worldgen_resources(CONFIG, namespace, type)))


@mcp.tool()
def validate_worldgen_references() -> str:
    """Check common datapack worldgen references and group related log issues."""
    return dumps(with_support(CONFIG, wg_validate_worldgen_references(CONFIG)))


@mcp.tool()
def worldgen_report() -> str:
    """Summarize worldgen resources, validation findings, and log-derived issues."""
    return dumps(with_support(CONFIG, wg_worldgen_report(CONFIG)))


@mcp.tool()
def search_datapack_files(query: str, namespace: str = "") -> str:
    """Search datapack files, including zip datapacks."""
    return dumps(with_support(CONFIG, dp_search_datapack_files(CONFIG, query, namespace)))


@mcp.tool()
def read_datapack_file(pack: str, inner_path: str) -> str:
    """Read a file from a folder or zip datapack."""
    return dp_read_datapack_file(CONFIG, pack, inner_path)


@mcp.tool()
def write_datapack_file(pack: str, inner_path: str, content: str) -> str:
    """Write a file into a folder or zip datapack with backup."""
    return dp_write_datapack_file(CONFIG, pack, inner_path, content)


@mcp.tool()
def scan_regions(dimension: str = "overworld") -> str:
    """Scan region files and chunk counts for a dimension."""
    return dumps(with_support(CONFIG, anvil_scan_regions(CONFIG, dimension)))


@mcp.tool()
def inspect_chunk(cx: int, cz: int, dimension: str = "overworld") -> str:
    """Inspect one Anvil chunk by chunk coordinates."""
    return dumps(with_support(CONFIG, anvil_inspect_chunk(CONFIG, cx, cz, dimension)))


@mcp.tool()
def get_block(x: int, y: int, z: int, dimension: str = "overworld") -> str:
    """Read one block id from an Anvil region."""
    return dumps(with_support(CONFIG, {"block": anvil_get_block(CONFIG, x, y, z, dimension)}))


@mcp.tool()
def read_block_box(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, dimension: str = "overworld", include_air: bool = False, confirm: bool = False) -> str:
    """Read blocks from a box. Large boxes require confirm=true."""
    return dumps(with_support(CONFIG, anvil_read_block_box(CONFIG, x1, y1, z1, x2, y2, z2, dimension, include_air, confirm)))


@mcp.tool()
def summarize_chunk_palette(cx: int, cz: int, dimension: str = "overworld") -> str:
    """Count block states in one chunk."""
    return dumps(with_support(CONFIG, anvil_summarize_chunk_palette(CONFIG, cx, cz, dimension)))


@mcp.tool()
def write_chunk_nbt_value(cx: int, cz: int, path: str, snbt_value: str, dimension: str = "overworld") -> str:
    """Write one SNBT value into a chunk NBT path."""
    return dumps(with_support(CONFIG, world_write_chunk_nbt_value(CONFIG, cx, cz, path, snbt_value, dimension)))


@mcp.tool()
def set_block(x: int, y: int, z: int, block_id: str, dimension: str = "overworld") -> str:
    """Set one block id in an Anvil region with backup."""
    return dumps(with_support(CONFIG, anvil_set_block(CONFIG, x, y, z, block_id, dimension)))


@mcp.tool()
def fill_blocks(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, block_id: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Fill a block box. Large edits require confirm=true."""
    return dumps(with_support(CONFIG, anvil_fill_blocks(CONFIG, x1, y1, z1, x2, y2, z2, block_id, dimension, confirm)))


@mcp.tool()
def replace_blocks(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, old_block: str, new_block: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Replace blocks in a box. Large edits require confirm=true."""
    return dumps(with_support(CONFIG, anvil_replace_blocks(CONFIG, x1, y1, z1, x2, y2, z2, old_block, new_block, dimension, confirm)))


@mcp.tool()
def set_biome_box(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, biome: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Set biome palette cells in a box for Java 1.20.1 chunks."""
    return dumps(with_support(CONFIG, world_set_biome_box(CONFIG, x1, y1, z1, x2, y2, z2, biome, dimension, confirm)))


@mcp.tool()
def refresh_heightmaps(chunks: list[dict[str, int]], dimension: str = "overworld", confirm: bool = False) -> str:
    """Clear heightmaps in selected chunks so Minecraft can rebuild them on load."""
    return dumps(with_support(CONFIG, world_refresh_heightmaps(CONFIG, chunks, dimension, confirm)))


@mcp.tool()
def edit_block_entity(x: int, y: int, z: int, nbt_path: str, snbt_value: str, dimension: str = "overworld") -> str:
    """Edit one NBT value on a block entity at exact world coordinates."""
    return dumps(with_support(CONFIG, world_edit_block_entity(CONFIG, x, y, z, nbt_path, snbt_value, dimension)))


@mcp.tool()
def add_block_entity(x: int, y: int, z: int, block_state: str, block_entity_snbt: str, dimension: str = "overworld") -> str:
    """Place a block and write/replace its block entity NBT."""
    return dumps(with_support(CONFIG, world_add_block_entity(CONFIG, x, y, z, block_state, block_entity_snbt, dimension)))


@mcp.tool()
def list_entities(dimension: str = "overworld", entity_id: str = "", max_entities: int = 200) -> str:
    """List entities from external entity region files."""
    return dumps(with_support(CONFIG, world_list_entities(CONFIG, dimension, entity_id, max_entities)))


@mcp.tool()
def add_entity(entity_snbt: str, dimension: str = "overworld") -> str:
    """Append an entity compound to the existing entity chunk selected by its Pos."""
    return dumps(with_support(CONFIG, world_add_entity(CONFIG, entity_snbt, dimension)))


@mcp.tool()
def edit_entity(uuid: str, nbt_path: str, snbt_value: str, dimension: str = "overworld") -> str:
    """Edit one NBT value on an entity by UUID."""
    return dumps(with_support(CONFIG, world_edit_entity(CONFIG, uuid, nbt_path, snbt_value, dimension)))


@mcp.tool()
def delete_entities(entity_id: str, dimension: str = "overworld", max_delete: int = 50, confirm: bool = False) -> str:
    """Delete entities by exact entity id from external entity region files."""
    return dumps(with_support(CONFIG, world_delete_entities(CONFIG, entity_id, dimension, max_delete, confirm)))


@mcp.tool()
def list_poi(dimension: str = "overworld", poi_type: str = "", max_poi: int = 200) -> str:
    """List POI records from POI region files."""
    return dumps(with_support(CONFIG, world_list_poi(CONFIG, dimension, poi_type, max_poi)))


@mcp.tool()
def delete_poi(poi_type: str, dimension: str = "overworld", max_delete: int = 100, confirm: bool = False) -> str:
    """Delete POI records by exact type."""
    return dumps(with_support(CONFIG, world_delete_poi(CONFIG, poi_type, dimension, max_delete, confirm)))


@mcp.tool()
def prune_chunks(chunks: list[dict[str, int]], dimension: str = "overworld", include_entities: bool = True, include_poi: bool = True, confirm: bool = False) -> str:
    """Delete selected chunks from region, entity, and POI files. Requires confirm=true."""
    return dumps(with_support(CONFIG, world_prune_chunks(CONFIG, chunks, dimension, include_entities, include_poi, confirm)))


@mcp.tool()
def list_structure_templates() -> str:
    """List structure NBT templates."""
    return dumps(tmpl_list_structure_templates(CONFIG))


@mcp.tool()
def read_structure_template(relative_path: str, nbt_path: str = "") -> str:
    """Read a structure NBT template."""
    return tmpl_read_structure_template(CONFIG, relative_path, nbt_path)


@mcp.tool()
def write_structure_template(relative_path: str, raw_bytes_base16: str) -> str:
    """Write a raw .nbt structure template from base16 bytes."""
    return tmpl_write_structure_template(CONFIG, relative_path, raw_bytes_base16)


@mcp.tool()
def write_structure_template_value(relative_path: str, nbt_path: str, snbt_value: str) -> str:
    """Write one SNBT value inside a structure template."""
    return tmpl_write_structure_template_value(CONFIG, relative_path, nbt_path, snbt_value)


@mcp.tool()
def export_region_to_template(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, output_path: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Export a block box to a vanilla structure template."""
    return tmpl_export_region_to_template(CONFIG, x1, y1, z1, x2, y2, z2, output_path, dimension, confirm)


@mcp.tool()
def place_template_to_region(template_path: str, x: int, y: int, z: int, dimension: str = "overworld", confirm: bool = False) -> str:
    """Place a vanilla structure template into Anvil regions."""
    return tmpl_place_template_to_region(CONFIG, template_path, x, y, z, dimension, confirm)


@mcp.tool()
def render_map_preview(x1: int, z1: int, x2: int, z2: int, y_mode: str = "surface", dimension: str = "overworld") -> str:
    """Render a top-down offline PNG preview from region data."""
    return dumps(with_support(CONFIG, preview_render_map_preview(CONFIG, x1, z1, x2, z2, y_mode, dimension)))


@mcp.tool()
def render_slice_preview(axis: str, fixed: int, min_a: int, max_a: int, min_y: int, max_y: int, dimension: str = "overworld") -> str:
    """Render a vertical offline PNG slice from region data."""
    return dumps(with_support(CONFIG, preview_render_slice_preview(CONFIG, axis, fixed, min_a, max_a, min_y, max_y, dimension)))


@mcp.tool()
def render_template_preview(template_path: str, axis: str = "y") -> str:
    """Render an offline PNG projection for a structure template."""
    return dumps(preview_render_template_preview(CONFIG, template_path, axis))


@mcp.tool()
def create_backup(relative_paths: list[str], reason: str = "manual backup") -> str:
    """Create a backup for selected safe paths without modifying them."""
    files = [resolve_under_root(CONFIG, path, write=True) for path in relative_paths]
    backup = begin_write(CONFIG, reason, files)
    backup.write_manifest()
    return dumps({"ok": True, "backup": str(backup.root)})


@mcp.tool()
def list_backups() -> str:
    """List mc-world-mcp backups."""
    root = CONFIG.backup_root
    if not root.exists():
        return dumps([])
    return dumps([
        {"name": path.name, "path": str(path), "manifest": (path / "manifest.json").exists()}
        for path in sorted(root.iterdir(), reverse=True)
        if path.is_dir()
    ])


@mcp.tool()
def restore_backup_manifest(backup_name: str) -> str:
    """Restore files recorded in one backup manifest after offline checks."""
    backup_dir = (CONFIG.backup_root / backup_name).resolve()
    backup_dir.relative_to(CONFIG.backup_root.resolve())
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = [CONFIG.root / entry["source"] for entry in manifest.get("entries", []) if entry.get("status") == "copied"]
    begin_write(CONFIG, f"restore_backup_manifest {backup_name}", targets)
    restored = 0
    for entry in manifest.get("entries", []):
        if entry.get("status") != "copied":
            continue
        src = backup_dir / entry["backup"]
        dst = CONFIG.root / entry["source"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored += 1
    return dumps({"ok": True, "restored": restored})


def main() -> None:
    if "--help" in sys.argv or "-h" in sys.argv:
        print("mc-world-mcp: offline-only Minecraft server/world MCP stdio server")
        print("Set MC_SERVER_ROOT to the server root before launching.")
        return
    mcp.run()


if __name__ == "__main__":
    main()
