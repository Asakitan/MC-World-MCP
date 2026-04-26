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
from .anvil import scan_regions as anvil_scan_regions
from .anvil import set_block as anvil_set_block
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
from .safety import assert_offline, begin_write, java_processes
from .templates import export_region_to_template as tmpl_export_region_to_template
from .templates import list_structure_templates as tmpl_list_structure_templates
from .templates import place_template_to_region as tmpl_place_template_to_region
from .templates import read_structure_template as tmpl_read_structure_template
from .templates import write_structure_template as tmpl_write_structure_template
from .templates import write_structure_template_value as tmpl_write_structure_template_value


CONFIG = load_config()

mcp = FastMCP(
    "mc-world",
    instructions=(
        "Offline-only Minecraft server/world MCP. No RCON, no sockets, no online player commands. "
        "Use it for local server files, NBT, datapacks, structure templates, logs, backups, and Anvil region edits. "
        "All write tools require the server to be offline and create backups."
    ),
)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def server_properties() -> dict[str, str]:
    path = CONFIG.root / "server.properties"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


@mcp.tool()
def server_summary() -> str:
    """Return a local summary of the configured Minecraft server root."""
    props = server_properties()
    world = CONFIG.root / props.get("level-name", "world")
    return dumps({
        "version": __version__,
        "server_root": str(CONFIG.root),
        "configured_level_name": props.get("level-name"),
        "default_world_path": str(CONFIG.world),
        "server_properties_world_path": str(world),
        "world_exists": CONFIG.world.exists(),
        "server_properties_world_exists": world.exists(),
        "datapacks": len(list((CONFIG.world / "datapacks").iterdir())) if (CONFIG.world / "datapacks").exists() else 0,
        "logs_latest_exists": (CONFIG.root / "logs" / "latest.log").exists(),
        "java_processes": java_processes(),
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
    return dumps({"ok": ok, "error": error, "java_processes": java_processes(), "world": str(CONFIG.world)})


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
    return nbt_read_nbt_file(CONFIG, "world/level.dat", path, max_depth)


@mcp.tool()
def write_level_dat_value(path: str, snbt_value: str) -> str:
    """Write one SNBT value into world/level.dat."""
    return nbt_write_nbt_value(CONFIG, "world/level.dat", path, snbt_value)


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
    return dumps(dp_list_datapacks(CONFIG))


@mcp.tool()
def validate_datapacks() -> str:
    """Validate datapack JSON and unexpected duplicate resources."""
    return dumps(dp_validate_datapacks(CONFIG))


@mcp.tool()
def search_datapack_files(query: str, namespace: str = "") -> str:
    """Search datapack files, including zip datapacks."""
    return dumps(dp_search_datapack_files(CONFIG, query, namespace))


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
    return dumps(anvil_scan_regions(CONFIG, dimension))


@mcp.tool()
def inspect_chunk(cx: int, cz: int, dimension: str = "overworld") -> str:
    """Inspect one Anvil chunk by chunk coordinates."""
    return dumps(anvil_inspect_chunk(CONFIG, cx, cz, dimension))


@mcp.tool()
def get_block(x: int, y: int, z: int, dimension: str = "overworld") -> str:
    """Read one block id from an Anvil region."""
    return dumps({"block": anvil_get_block(CONFIG, x, y, z, dimension)})


@mcp.tool()
def set_block(x: int, y: int, z: int, block_id: str, dimension: str = "overworld") -> str:
    """Set one block id in an Anvil region with backup."""
    return dumps(anvil_set_block(CONFIG, x, y, z, block_id, dimension))


@mcp.tool()
def fill_blocks(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, block_id: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Fill a block box. Large edits require confirm=true."""
    return dumps(anvil_fill_blocks(CONFIG, x1, y1, z1, x2, y2, z2, block_id, dimension, confirm))


@mcp.tool()
def replace_blocks(x1: int, y1: int, z1: int, x2: int, y2: int, z2: int, old_block: str, new_block: str, dimension: str = "overworld", confirm: bool = False) -> str:
    """Replace blocks in a box. Large edits require confirm=true."""
    return dumps(anvil_replace_blocks(CONFIG, x1, y1, z1, x2, y2, z2, old_block, new_block, dimension, confirm))


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

