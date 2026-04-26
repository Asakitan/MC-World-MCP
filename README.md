# MC World MCP

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
- reject writes when a `java` or `javaw` process is running
- reject Java world writes unless the selected world is DataVersion 3465
- back up every modified file under `backup/mc_world_mcp/<timestamp>/`
- write a `manifest.json` describing the changed files

Read tools are allowed while the server is running.

## Tool Groups

- Server/files: summaries, safe file read/write, logs, version/platform detection
- NBT: `level.dat`, player data, world data, structure NBT
- Datapacks: folder and zip datapack listing, validation, search, read, write
- Regions: scan, inspect chunks, get/read/set/fill/replace blocks, block state strings
- World diagnostics: dimensions, world coverage, chunk palettes, log issue grouping
- World data: block entities, external entity regions, POI regions, biome boxes, heightmap clearing, chunk pruning
- Templates: list/read/write `.nbt` structure templates, export/place blocks with block entities and best-effort entities
- Safety: offline checks, backup listing, backup restore
