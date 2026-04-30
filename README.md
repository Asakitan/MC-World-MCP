# MC-World-MCP

Offline-only MCP tools for operating on a Minecraft server directory.

This MCP intentionally does not use RCON, sockets, online player queries, or server start/stop controls. It only reads and writes local files such as `level.dat`, datapacks, structure templates, logs, and Anvil region files.

The complete write path targets Java Edition / Arclight 1.20.1 and 1.21.1
worlds with `DataVersion` 3465 or 3955. Other Java Anvil worlds are detected and
exposed for best-effort reads, but world writes are rejected unless the version
adapter marks them as fully supported. Bedrock LevelDB worlds are detected as
unsupported.

## Run

When this project lives at `E:/VC/mc-world-mcp` and a server workspace lives two levels below `E:/VC`, the workspace `.vscode/mcp.json` starts the server with:

```json
{
  "command": "python",
  "args": ["-m", "mc_world_mcp.server"],
  "env": {
    "PYTHONPATH": "${workspaceFolder}/../mc-world-mcp/src",
    "MC_SERVER_ROOT": "${workspaceFolder}"
  }
}
```

`MC_SERVER_ROOT` may point at either the Arclight server root that contains
`server.properties` and `world/`, or at a workspace/modpack root that contains a
`server/` subdirectory. Assistants can also call `discover_server_roots()` and
`select_server_root()` to choose the active server root at runtime.

World selection follows `server.properties` `level-name`, so a server using
`level-name=world_regen_source` is operated through that directory rather than a
hardcoded `world/`. Set `MC_WORLD_NAME` to override this explicitly.

## Safety

All write tools:

- reject paths outside `MC_SERVER_ROOT`
- reject writes when a server or unknown `java`/`javaw` process is running; recognized Minecraft client Java processes are ignored
- reject Java world writes unless the selected world is DataVersion 3465 or 3955
- back up every modified file under `backup/mc_world_mcp/<timestamp>/`
- write a `manifest.json` describing the changed files

Read tools are allowed while the server is running.

## Tool Groups

- Server/files: summaries, safe file read/write, logs, version/platform detection
- Source worlds: local world inventory, server-generation workflow guidance, source/target chunk comparison, and offline chunk import
- NBT: `level.dat`, player data, world data, structure NBT
- Datapacks: folder and zip datapack listing, validation, search, read, write
- Worldgen: datapack/mod/plugin interface listing, resource checks, source-world simulation, and report summaries
- Regions: scan, inspect chunks, get/read/set/fill/replace blocks, block state strings
- World diagnostics: dimensions, world coverage, chunk palettes, log issue grouping
- World data: block entities, external entity regions, POI regions, biome boxes, heightmap clearing, chunk pruning
- Templates: list/read/write `.nbt` structure templates, export/place blocks with block entities and best-effort entities
- Preview: offline PNG map, slice, and structure-template previews under `backup/mc_world_mcp/previews/`
- Safety: offline checks, backup listing, backup restore

## Optional Preview Acceleration

Preview rendering and source-world generation simulation have pure-Python
fallbacks and can optionally use a compiled Cython module for hot loops such as
block-state index decoding, chunk surface projection, close-up side sampling,
source-world floor projection, structure-template projection, and item-NBT
multi-view recomputation.

On Windows, compile the extension in place:

```powershell
python setup.py build_ext --inplace
```

The source distribution includes generated C code, so Cython is optional for
normal builds. Install `mc-world-mcp[preview-accel]` or `python -m pip install
Cython` only when you want to regenerate the C file from `_preview_accel.pyx`.
For wheel builds, set `MC_WORLD_MCP_BUILD_ACCEL=1` to opt in to compiling the
extension.

This creates a platform-specific `mc_world_mcp._preview_accel.pyd` next to the
Python sources. If the compiled module is present, preview and simulation tools
load it automatically; otherwise they continue using the pure-Python
implementation.
Building the `.pyd` requires the Microsoft C++ Build Tools matching the active
Python version.

The repository may include a prebuilt
`src/mc_world_mcp/_preview_accel.cp311-win_amd64.pyd` for Windows x64 CPython
3.11. Other Python versions, platforms, or architectures should rebuild the
extension locally.

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
   - Command syntax: call `get_wiki_command_info`, then `spyglass_get_commands` when exact version syntax matters.
   - IDs and registries: call `spyglass_get_registries` for blocks, items, entities, biomes, enchantments, and other registries.
   - Vanilla JSON: call Misode tools such as `misode_get_preset_data`, `misode_get_presets`, `misode_get_loot_tables`, and `misode_get_recipes`.
   - Wiki background: call `search_wiki`, then `get_wiki_page_content`.

3. Use `mc-world` for local server and world operations.
   - Start with `server_summary()`, `discover_server_roots()` / `select_server_root()` when the root is wrong, `detect_world_version()`, `world_summary()`, and `check_offline_safety()`.
   - For datapacks, use `list_datapacks()`, `validate_datapacks()`, `search_datapack_files()`, `read_datapack_file()`, and `write_datapack_file()`.
   - For worldgen diagnosis, use `list_generation_interfaces()`, `worldgen_report()`, `list_worldgen_resources()`, and `validate_worldgen_references()`.
   - For logs, use `analyze_latest_log()`, `read_server_log()`, and `grep_server_log()`.
   - For Anvil data, use `scan_regions()`, `scan_world_coverage()`, `inspect_chunk()`, `summarize_chunk_palette()`, `get_block()`, `read_block_box()`, `set_block()`, `fill_blocks()`, and `replace_blocks()`.
   - For NBT edits, use `read_level_dat()`, `write_level_dat_value()`, `read_nbt_file()`, `write_nbt_value()`, and `write_chunk_nbt_value()`.
   - For entities, block entities, POI, biomes, and heightmaps, use `list_entities()`, `add_entity()`, `edit_entity()`, `delete_entities()`, `add_block_entity()`, `edit_block_entity()`, `list_poi()`, `delete_poi()`, `set_biome_box()`, and `refresh_heightmaps()`.
   - For structures, use `list_structure_templates()`, `read_structure_template()`, `write_structure_template()`, `write_structure_template_value()`, `export_region_to_template()`, and `place_template_to_region()`.
   - For previews, use `render_map_preview()`, `render_closeup_map_preview()`, `render_slice_preview()`, `render_template_preview()`, and `render_item_nbt_preview()`.
   - For backups, use `create_backup()`, `list_backups()`, and `restore_backup_manifest()`.

4. Respect the `mc-world` safety boundary.
   - Do not use RCON, sockets, online player queries, or server start/stop controls.
   - Read tools may run while the server is online.
   - Write tools require the server to be offline and will reject writes while server or unknown `java`/`javaw` processes are running. Recognized Minecraft client Java processes are ignored.
   - World writes are supported only for Java Anvil `DataVersion` 3465 or 3955.
   - Every write creates a backup under `backup/mc_world_mcp/<timestamp>/` with `manifest.json`.

5. Use source worlds for real datapack, mod, or plugin worldgen.
   - `mc-world` does not execute biome modifiers, jigsaw placement, datapack worldgen, mod worldgen, or plugin worldgen.
   - `list_generation_interfaces()` exposes the open datapack, mod jar, and plugin jar generation inputs visible to the server.
   - Generate chunks in Minecraft/Arclight first, then stop the server.
   - Select the target world with `MC_WORLD_NAME`, for example `MC_WORLD_NAME=world`.
   - Use `worldgen_source_plan("world_regen_source")`, `list_local_worlds()`, `simulate_worldgen_generation(...)`, and `compare_world_chunks(...)` before importing.
   - Use `import_chunks_from_world("world_regen_source", chunks, confirm=true)` only after confirming the source and target are different worlds.

6. Recommended diagnosis workflows.
   - Datapack load issue: `validate_datapacks()` -> `worldgen_report()` -> `analyze_latest_log()` -> `search_datapack_files()` -> `read_datapack_file()`.
   - Structure generation issue: `list_generation_interfaces()` -> `worldgen_report()` -> `list_worldgen_resources(type="worldgen/structure")` -> `validate_worldgen_references()` -> `simulate_worldgen_generation(...)` -> `read_level_dat("Data.WorldGenSettings")` -> `grep_server_log("structure")`.
   - Map visual check: `scan_world_coverage()` -> `render_map_preview(..., "top")` -> `render_map_preview(..., "ocean_floor")` -> `inspect_chunk()` or `summarize_chunk_palette()`.
   - Offline edit: `check_offline_safety()` -> create or rely on automatic backup -> perform one focused write -> render or inspect the affected area.

## Current Server Workflow

For the current Arclight server workspace, `server.properties` controls the
active world through `level-name`. With the README MCP config above, all world
tools automatically target that active world instead of a hardcoded `world/`.

This MCP still does not execute Minecraft worldgen. Datapack biome modifiers,
jigsaw structures, mod structures, plugin-provided generation, coral placement,
and sand dunes must be generated by Minecraft/Arclight in a source world first.
The MCP can then inspect that generated source world offline, simulate the result
from the generated files, and copy selected generated chunks into the active
target world.

For import work, launch the MCP with the target world selected, for example
`MC_WORLD_NAME=world`, and pass the generated source world as
`source_world_name="world_regen_source"`. The source and target worlds must be
different local directories.

Useful checks:

- `worldgen_report()` summarizes datapacks, worldgen resources, validation findings, and log-derived resource issues.
- `list_generation_interfaces()` summarizes datapack resources plus mod/plugin jar generation interfaces and metadata.
- `validate_worldgen_references()` finds common missing same-namespace worldgen and structure references.
- `list_local_worlds()` lists source and target world directories under the server root.
- `worldgen_source_plan("world_regen_source")` explains the safe source-world generation/import workflow.
- `simulate_worldgen_generation("world_regen_source", min_cx, min_cz, max_cx, max_cz)` treats server-generated source chunks as a simulation sample, returns success/completeness signals, Cython acceleration status, block/height summaries, and preview PNG paths.
- `compare_world_chunks("world_regen_source", min_cx, min_cz, max_cx, max_cz)` shows which generated source chunks exist and which target chunks would be overwritten.
- `import_chunks_from_world("world_regen_source", [{"cx": 0, "cz": 0}], confirm=true)` copies terrain, entity, and POI chunk records from an already-generated source world into the active world.
- `write_chunk_nbt_value(cx, cz, path, snbt_value)` edits one chunk NBT path while offline.
- `add_block_entity(x, y, z, block_state, block_entity_snbt)` places a block and writes its block entity NBT.
- `add_entity(entity_snbt)` appends an entity to an existing external entity chunk selected by its `Pos`.

Offline visual checks:

- `render_map_preview(x1, z1, x2, z2, "surface")` renders a top-down PNG. `y_mode` also accepts `top`, `ocean_floor`, `seafloor`, or an integer Y level such as `"26"`. Previews can render up to 1,048,576 output pixels; pass `sample=2` or higher for faster downsampled overviews of larger areas.
- `render_closeup_map_preview(x1, z1, x2, z2, "surface", view="oblique", side_depth=32)` renders a close-up pseudo-3D terrain PNG from real Anvil columns, including visible top faces, height differences, and side faces. Views include `oblique`, `south_east`, `south_west`, `north_west`, and `north_east`; side faces sample real blocks below each top face up to `side_depth` layers instead of extending the top block through the whole column. The result reports whether Cython accelerated the close-up recomputation.
- `render_slice_preview("x", fixed, min_z, max_z, min_y, max_y)` renders a vertical slice.
- `render_template_preview(template_path)` renders a structure `.nbt` projection.
- `render_item_nbt_preview(item_snbt, views=["front", "oblique"])` renders an item stack SNBT/NBT preview from local resource-pack, mod, plugin, or datapack assets. Views include `front`, `back`, `left`, `right`, `top`, `bottom`, `isometric`, and `oblique`; the result reports whether Cython accelerated the view recomputation.

Preview tools are read-only against the world data and write PNG files under
`backup/mc_world_mcp/previews/<timestamp>/`.
