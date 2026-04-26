# MC World MCP

Offline-only MCP tools for operating on a Minecraft server directory.

This MCP intentionally does not use RCON, sockets, online player queries, or server start/stop controls. It only reads and writes local files such as `level.dat`, datapacks, structure templates, logs, and Anvil region files.

## Run

The workspace `.vscode/mcp.json` starts the server with:

```json
{
  "command": "python",
  "args": ["-m", "mc_world_mcp.server"],
  "env": {
    "PYTHONPATH": "${workspaceFolder}/mc-world-mcp/src",
    "MC_SERVER_ROOT": "${workspaceFolder}"
  }
}
```

`MC_SERVER_ROOT` should point at the Arclight server root that contains `server.properties` and `world/`.

## Safety

All write tools:

- reject paths outside `MC_SERVER_ROOT`
- reject writes when a `java` or `javaw` process is running
- back up every modified file under `backup/mc_world_mcp/<timestamp>/`
- write a `manifest.json` describing the changed files

Read tools are allowed while the server is running.

## Tool Groups

- Server/files: summaries, safe file read/write, logs
- NBT: `level.dat`, player data, world data, structure NBT
- Datapacks: folder and zip datapack listing, validation, search, read, write
- Regions: scan, inspect chunks, get/set/fill/replace blocks
- Templates: list/read/write `.nbt` structure templates
- Safety: offline checks, backup listing, backup restore

