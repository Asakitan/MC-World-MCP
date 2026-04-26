# MC-World-MCP

Offline-only MCP tools for operating on a Minecraft server directory.

This MCP intentionally does not use RCON, sockets, online player queries, or server start/stop controls. It only reads and writes local files such as `level.dat`, datapacks, structure templates, logs, and Anvil region files.

The complete write path targets Java Edition / Arclight 1.20.1 worlds with
`DataVersion` 3465. Other Java Anvil worlds are detected and exposed for
best-effort reads, but world writes are rejected unless the version adapter marks
them as fully supported. Bedrock LevelDB worlds are detected as unsupported.

## Run

When this project lives at `E:/VC/mc-world-mcp` and a server workspace lives two levels below `E:/VC`, the workspace `.vscode/mcp.json` starts the server with:

```json
{
  "command": "python",
  "args": ["-m", "mc_world_mcp.server"],
  "env": {
    "PYTHONPATH": "${workspaceFolder}/../../mc-world-mcp/src",
    "MC_SERVER_ROOT": "${workspaceFolder}"
  }
}
```

`MC_SERVER_ROOT` should point at the Arclight server root that contains `server.properties` and `world/`. If it is omitted, the server tries the current working directory first.

World selection follows `server.properties` `level-name`, so a server using
`level-name=world_regen_source` is operated through that directory rather than a
hardcoded `world/`. Set `MC_WORLD_NAME` to override this explicitly.

## Safety

All write tools:

- reject paths outside `MC_SERVER_ROOT`
- reject writes when a server or unknown `java`/`javaw` process is running; recognized Minecraft client Java processes are ignored
- reject Java world writes unless the selected world is DataVersion 3465
- back up every modified file under `backup/mc_world_mcp/<timestamp>/`
- write a `manifest.json` describing the changed files

Read tools are allowed while the server is running.

## Tool Groups

- Server/files: summaries, safe file read/write, logs, version/platform detection
- Source worlds: local world inventory, server-generation workflow guidance, source/target chunk comparison, and offline chunk import
- NBT: `level.dat`, player data, world data, structure NBT
- Datapacks: folder and zip datapack listing, validation, search, read, write
- Worldgen: resource listing, common reference checks, and report summaries for datapack world generation
- Regions: scan, inspect chunks, get/read/set/fill/replace blocks, block state strings
- World diagnostics: dimensions, world coverage, chunk palettes, log issue grouping
- World data: block entities, external entity regions, POI regions, biome boxes, heightmap clearing, chunk pruning
- Templates: list/read/write `.nbt` structure templates, export/place blocks with block entities and best-effort entities
- Preview: offline PNG map, slice, and structure-template previews under `backup/mc_world_mcp/previews/`
- Safety: offline checks, backup listing, backup restore

## Assistant MCP Instructions

AI assistants working on this Minecraft workspace should use MCP tools in this order:

0. Read MCP-provided instructions.
   - The `mc-world` server exposes this guidance in its server instructions.
   - Call `assistant_instructions()` first when tool choice or workflow is unclear.
   - MCP clients that support resources can read `mc-world://assistant-instructions`.
   - MCP clients that support prompts can use `mc_world_assistant_instructions`.

1. Read project context first.
   - Read Copilot repo memory when available, especially project overview, datapacks, tool reference, gotchas, change history, and MCP server notes.
   - Then read local files such as `README.md`, `.github/copilot-instructions.md`, `server.properties`, datapack files, and logs as needed.

2. Use `minecode` for Minecraft reference lookups.
   - Command syntax: call `get_wiki_command_info`, then `spyglass_get_commands` when exact 1.20.1 syntax matters.
   - IDs and registries: call `spyglass_get_registries` for blocks, items, entities, biomes, enchantments, and other registries.
   - Vanilla JSON: call Misode tools such as `misode_get_preset_data`, `misode_get_presets`, `misode_get_loot_tables`, and `misode_get_recipes`.
   - Wiki background: call `search_wiki`, then `get_wiki_page_content`.

3. Use `mc-world` for local server and world operations.
   - Start with `server_summary()`, `detect_world_version()`, `world_summary()`, and `check_offline_safety()`.
   - For datapacks, use `list_datapacks()`, `validate_datapacks()`, `search_datapack_files()`, `read_datapack_file()`, and `write_datapack_file()`.
   - For worldgen diagnosis, use `worldgen_report()`, `list_worldgen_resources()`, and `validate_worldgen_references()`.
   - For logs, use `analyze_latest_log()`, `read_server_log()`, and `grep_server_log()`.
   - For Anvil data, use `scan_regions()`, `scan_world_coverage()`, `inspect_chunk()`, `summarize_chunk_palette()`, `get_block()`, `read_block_box()`, `set_block()`, `fill_blocks()`, and `replace_blocks()`.
   - For NBT edits, use `read_level_dat()`, `write_level_dat_value()`, `read_nbt_file()`, `write_nbt_value()`, and `write_chunk_nbt_value()`.
   - For entities, block entities, POI, biomes, and heightmaps, use `list_entities()`, `add_entity()`, `edit_entity()`, `delete_entities()`, `add_block_entity()`, `edit_block_entity()`, `list_poi()`, `delete_poi()`, `set_biome_box()`, and `refresh_heightmaps()`.
   - For structures, use `list_structure_templates()`, `read_structure_template()`, `write_structure_template()`, `write_structure_template_value()`, `export_region_to_template()`, and `place_template_to_region()`.
   - For previews, use `render_map_preview()`, `render_slice_preview()`, and `render_template_preview()`.
   - For backups, use `create_backup()`, `list_backups()`, and `restore_backup_manifest()`.

4. Respect the `mc-world` safety boundary.
   - Do not use RCON, sockets, online player queries, or server start/stop controls.
   - Read tools may run while the server is online.
   - Write tools require the server to be offline and will reject writes while server or unknown `java`/`javaw` processes are running. Recognized Minecraft client Java processes are ignored.
   - World writes are supported only for Java Anvil `DataVersion` 3465.
   - Every write creates a backup under `backup/mc_world_mcp/<timestamp>/` with `manifest.json`.

5. Use source worlds for real datapack or mod worldgen.
   - `mc-world` does not execute biome modifiers, jigsaw placement, datapack worldgen, or mod worldgen.
   - Generate chunks in Minecraft/Arclight first, then stop the server.
   - Select the target world with `MC_WORLD_NAME`, for example `MC_WORLD_NAME=world`.
   - Use `worldgen_source_plan("world_regen_source")`, `list_local_worlds()`, and `compare_world_chunks(...)` before importing.
   - Use `import_chunks_from_world("world_regen_source", chunks, confirm=true)` only after confirming the source and target are different worlds.

6. Recommended diagnosis workflows.
   - Datapack load issue: `validate_datapacks()` -> `worldgen_report()` -> `analyze_latest_log()` -> `search_datapack_files()` -> `read_datapack_file()`.
   - Structure generation issue: `worldgen_report()` -> `list_worldgen_resources(type="worldgen/structure")` -> `validate_worldgen_references()` -> `read_level_dat("Data.WorldGenSettings")` -> `grep_server_log("structure")`.
   - Map visual check: `scan_world_coverage()` -> `render_map_preview(..., "top")` -> `render_map_preview(..., "ocean_floor")` -> `inspect_chunk()` or `summarize_chunk_palette()`.
   - Offline edit: `check_offline_safety()` -> create or rely on automatic backup -> perform one focused write -> render or inspect the affected area.

## Current Server Workflow

For the current Arclight 1.20.1 server workspace, `server.properties` uses
`level-name=world_regen_source`. With the README MCP config above, all world
tools automatically target that active world instead of the default `world/`.

This MCP still does not execute Minecraft worldgen. Datapack biome modifiers,
jigsaw structures, mod structures, coral placement, and sand dunes must be
generated by Minecraft/Arclight in a source world first. The MCP can then inspect
that generated source world offline and copy selected generated chunks into the
active target world.

For import work, launch the MCP with the target world selected, for example
`MC_WORLD_NAME=world`, and pass the generated source world as
`source_world_name="world_regen_source"`. The source and target worlds must be
different local directories.

Useful checks:

- `worldgen_report()` summarizes datapacks, worldgen resources, validation findings, and log-derived resource issues.
- `validate_worldgen_references()` finds common missing same-namespace worldgen and structure references.
- `list_local_worlds()` lists source and target world directories under the server root.
- `worldgen_source_plan("world_regen_source")` explains the safe source-world generation/import workflow.
- `compare_world_chunks("world_regen_source", min_cx, min_cz, max_cx, max_cz)` shows which generated source chunks exist and which target chunks would be overwritten.
- `import_chunks_from_world("world_regen_source", [{"cx": 0, "cz": 0}], confirm=true)` copies terrain, entity, and POI chunk records from an already-generated source world into the active world.
- `write_chunk_nbt_value(cx, cz, path, snbt_value)` edits one chunk NBT path while offline.
- `add_block_entity(x, y, z, block_state, block_entity_snbt)` places a block and writes its block entity NBT.
- `add_entity(entity_snbt)` appends an entity to an existing external entity chunk selected by its `Pos`.

Offline visual checks:

- `render_map_preview(x1, z1, x2, z2, "surface")` renders a top-down PNG. `y_mode` also accepts `top`, `ocean_floor`, `seafloor`, or an integer Y level such as `"26"`.
- `render_slice_preview("x", fixed, min_z, max_z, min_y, max_y)` renders a vertical slice.
- `render_template_preview(template_path)` renders a structure `.nbt` projection.

Preview tools are read-only against the world data and write PNG files under
`backup/mc_world_mcp/previews/<timestamp>/`.
