# Copilot / Assistant Instructions

This repository provides `mc-world-mcp`, an offline-only MCP server for Minecraft Java / Arclight 1.20.1 world files.

Before planning or editing meaningful work, read the project README and Copilot repo memory if available. Useful memory topics include project overview, datapacks, tools, technical gotchas, change history, and MCP server notes.

## MCP Servers

Use `minecode` for Minecraft reference data:

- Commands: `get_wiki_command_info`, then `spyglass_get_commands` for exact syntax.
- IDs and registries: `spyglass_get_registries`.
- Vanilla JSON: Misode tools such as `misode_get_preset_data`, `misode_get_presets`, `misode_get_loot_tables`, and `misode_get_recipes`.
- Wiki pages: `search_wiki`, then `get_wiki_page_content`.

Use `mc-world` for local server/world operations:

- First read the MCP-provided server instructions. If unsure, call `assistant_instructions()` or read the `mc-world://assistant-instructions` resource.
- Start with `server_summary()`, `detect_world_version()`, `world_summary()`, and `check_offline_safety()`.
- Diagnose datapacks with `list_datapacks()`, `validate_datapacks()`, `worldgen_report()`, `validate_worldgen_references()`, `search_datapack_files()`, and `read_datapack_file()`.
- Inspect logs with `analyze_latest_log()`, `read_server_log()`, and `grep_server_log()`.
- Inspect Anvil data with `scan_regions()`, `scan_world_coverage()`, `inspect_chunk()`, `summarize_chunk_palette()`, `get_block()`, and `read_block_box()`.
- Edit offline with focused tools such as `write_datapack_file()`, `write_nbt_value()`, `write_chunk_nbt_value()`, `set_block()`, `fill_blocks()`, `replace_blocks()`, `set_biome_box()`, `add_block_entity()`, and `add_entity()`.
- Preview with `render_map_preview()`, `render_slice_preview()`, and `render_template_preview()`.

## Safety Rules

- Never use RCON, sockets, online player queries, or server start/stop controls from this MCP workflow.
- Reads may run while the server is online.
- Writes require the server to be offline; `mc-world` rejects writes while server or unknown `java`/`javaw` processes are running, while recognized Minecraft client Java processes are ignored.
- World writes are supported only for Java Anvil `DataVersion` 3465.
- Every write creates `backup/mc_world_mcp/<timestamp>/manifest.json`.

## Source World Workflow

`mc-world` cannot execute datapack, jigsaw, biome modifier, or mod worldgen. For coral, sand dunes, Abyssal structures, and other generated content:

1. Generate chunks in Minecraft/Arclight with the correct datapacks and mods.
2. Stop the server.
3. Select the target world with `MC_WORLD_NAME`, for example `MC_WORLD_NAME=world`.
4. Use `list_local_worlds()`, `worldgen_source_plan("world_regen_source")`, and `compare_world_chunks(...)`.
5. Use `import_chunks_from_world("world_regen_source", chunks, confirm=true)` only after confirming source and target worlds differ.

## Preview Modes

For `render_map_preview()`, use:

- `top` or `surface` for top non-air blocks.
- `ocean_floor`, `seafloor`, `sea_floor`, or `floor` to skip air and water.
- A string integer such as `"26"` or `"-63"` for a fixed Y slice.
