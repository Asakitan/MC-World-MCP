from __future__ import annotations

from typing import Any


SERVER_INSTRUCTIONS = """
mc-world is an offline-only Minecraft Java / Arclight 1.20.1 world MCP.
Assistants should call assistant_instructions() first when they need workflow
guidance, then begin with server_summary(), detect_world_version(),
world_summary(), and check_offline_safety().

Safety boundary:
- Do not use RCON, sockets, online player queries, or server start/stop controls.
- Read tools may run while the server is online.
- Write tools require the server to be offline and reject writes while server or unknown Java processes are running; recognized Minecraft client Java processes are ignored.
- World writes are supported only for Java Anvil DataVersion 3465.
- Every write creates backup/mc_world_mcp/<timestamp>/manifest.json.

Worldgen boundary:
- This MCP does not execute datapack, jigsaw, biome modifier, or mod worldgen.
- Generate chunks in Minecraft/Arclight first, stop the server, then inspect or import.
- For source-world imports, select the target world with MC_WORLD_NAME and pass
  the generated source world to worldgen_source_plan(), compare_world_chunks(),
  and import_chunks_from_world(..., confirm=true).
""".strip()


def assistant_instruction_payload() -> dict[str, Any]:
    return {
        "read_first": [
            "Call assistant_instructions() when unsure which mc-world tool to use.",
            "Use server_summary(), detect_world_version(), world_summary(), and check_offline_safety() before planning writes.",
            "Use minecode MCP for Minecraft reference data; use mc-world MCP for local files and Anvil/NBT operations.",
        ],
        "safety_rules": [
            "No RCON, sockets, online player queries, or server start/stop controls.",
            "Read tools may run while the server is online.",
            "Write tools require the server to be offline; server or unknown Java processes cause writes to be rejected, while recognized Minecraft client Java processes are ignored.",
            "World writes are supported only for Java Anvil DataVersion 3465.",
            "Every write creates backup/mc_world_mcp/<timestamp>/manifest.json.",
        ],
        "tool_order": [
            {
                "goal": "Initial orientation",
                "tools": ["server_summary", "detect_world_version", "world_summary", "check_offline_safety"],
            },
            {
                "goal": "Datapack diagnosis",
                "tools": ["list_datapacks", "validate_datapacks", "worldgen_report", "validate_worldgen_references", "search_datapack_files", "read_datapack_file"],
            },
            {
                "goal": "Logs",
                "tools": ["analyze_latest_log", "read_server_log", "grep_server_log"],
            },
            {
                "goal": "Anvil/chunk inspection",
                "tools": ["scan_regions", "scan_world_coverage", "inspect_chunk", "summarize_chunk_palette", "get_block", "read_block_box"],
            },
            {
                "goal": "Offline world edits",
                "tools": ["write_nbt_value", "write_chunk_nbt_value", "set_block", "fill_blocks", "replace_blocks", "set_biome_box", "add_block_entity", "add_entity"],
            },
            {
                "goal": "Structure templates",
                "tools": ["list_structure_templates", "read_structure_template", "write_structure_template", "write_structure_template_value", "export_region_to_template", "place_template_to_region"],
            },
            {
                "goal": "Visual previews",
                "tools": ["render_map_preview", "render_slice_preview", "render_template_preview"],
            },
            {
                "goal": "Backups",
                "tools": ["create_backup", "list_backups", "restore_backup_manifest"],
            },
        ],
        "source_world_workflow": [
            "mc-world cannot execute Minecraft worldgen logic.",
            "Generate coral, dunes, Abyssal structures, jigsaw structures, datapack content, and mod content in Minecraft/Arclight first.",
            "Stop the server completely.",
            "Launch/select the target world with MC_WORLD_NAME, for example MC_WORLD_NAME=world.",
            "Call list_local_worlds() and worldgen_source_plan('world_regen_source').",
            "Call compare_world_chunks('world_regen_source', min_cx, min_cz, max_cx, max_cz).",
            "Only then call import_chunks_from_world('world_regen_source', chunks, confirm=true).",
        ],
        "preview_modes": {
            "top_or_surface": "Top non-air blocks; water surfaces remain visible.",
            "ocean_floor_or_seafloor": "Top block after skipping air and water.",
            "integer_string": "Fixed Y level, such as '26' or '-63'.",
        },
        "common_workflows": [
            {
                "name": "Datapack load issue",
                "steps": ["validate_datapacks", "worldgen_report", "analyze_latest_log", "search_datapack_files", "read_datapack_file"],
            },
            {
                "name": "Structure generation issue",
                "steps": ["worldgen_report", "list_worldgen_resources(type='worldgen/structure')", "validate_worldgen_references", "read_level_dat('Data.WorldGenSettings')", "grep_server_log('structure')"],
            },
            {
                "name": "Map visual check",
                "steps": ["scan_world_coverage", "render_map_preview(..., 'top')", "render_map_preview(..., 'ocean_floor')", "inspect_chunk", "summarize_chunk_palette"],
            },
            {
                "name": "Offline edit",
                "steps": ["check_offline_safety", "perform one focused write", "render or inspect affected area", "list_backups if rollback is needed"],
            },
        ],
    }


def assistant_instruction_markdown() -> str:
    payload = assistant_instruction_payload()
    sections = [
        "# mc-world MCP Assistant Instructions",
        "",
        "## Read First",
        *[f"- {item}" for item in payload["read_first"]],
        "",
        "## Safety Rules",
        *[f"- {item}" for item in payload["safety_rules"]],
        "",
        "## Source World Workflow",
        *[f"- {item}" for item in payload["source_world_workflow"]],
        "",
        "## Preview Modes",
        "- top/surface: top non-air blocks; water surfaces remain visible.",
        "- ocean_floor/seafloor/sea_floor/floor: top block after skipping air and water.",
        "- integer string: fixed Y level, such as '26' or '-63'.",
    ]
    return "\n".join(sections)
