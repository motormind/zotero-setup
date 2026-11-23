# 4. Zotero MCP for AI assistants

With an MCP server, Claude Code, Claude Desktop, Cursor & co. can use the library directly: search, fetch metadata/BibTeX, read full texts and PDF annotations, write notes, add papers.

Recommendation: **[54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp)** (MIT, actively maintained, supports group libraries).

> `zt` and MCP complement each other: `zt` for reproducible, scriptable steps (pushing from files, `references.bib`), MCP for interactive work with an assistant.

## Install

```bash
uv tool install zotero-mcp-server      # or: pipx install zotero-mcp-server
# optional: semantic search / PDF features
uv tool install "zotero-mcp-server[all]"
```

## Option A – Web API on the project group (recommended for teams)

Everybody sees the same group; also works in Codespaces / dev containers.

| Variable | Value |
|---|---|
| `ZOTERO_API_KEY` | your own key (from `.env`) |
| `ZOTERO_LIBRARY_ID` | group ID |
| `ZOTERO_LIBRARY_TYPE` | `group` |

## Option B – local (Zotero desktop running)

`ZOTERO_LOCAL=true` → **no key needed**, fast, full text/annotations from the local database. Requires Zotero → Settings → Advanced → "Allow other applications …". Hybrid: `ZOTERO_LOCAL=true` + web credentials = read locally, write via the Web API.

## Claude Code (per project)

`zt init --mcp` creates a `.mcp.json` (template: [`mcp.json`](../src/zotero_setup/templates/mcp.json)). It contains **only variable references**, no values – safe to commit:

```json
{
  "mcpServers": {
    "zotero": {
      "command": "zotero-mcp",
      "env": {
        "ZOTERO_LOCAL": "${ZOTERO_LOCAL:-false}",
        "ZOTERO_API_KEY": "${ZOTERO_API_KEY:-}",
        "ZOTERO_LIBRARY_ID": "${ZOTERO_LIBRARY_ID:-}",
        "ZOTERO_LIBRARY_TYPE": "${ZOTERO_LIBRARY_TYPE:-group}"
      }
    }
  }
}
```

Claude Code fills in `${…}` from the **shell environment**, not from `.env`. So load it before starting:

```bash
set -a; source .env; set +a     # set ZOTERO_LIBRARY_ID in .env as well
claude
```

…or permanently with [direnv](https://direnv.net/) (`.envrc`: `dotenv`).

Alternatively, just for yourself without a file in the repo:

```bash
claude mcp add zotero --scope local \
  -e ZOTERO_LIBRARY_TYPE=group -e ZOTERO_LIBRARY_ID=<GROUP_ID> -e ZOTERO_API_KEY=<KEY> \
  -- zotero-mcp
```

(`--scope local` stores it in your personal `~/.claude.json`, not in the repo.)

Check: run `/mcp` in Claude Code → `zotero` should be connected.

Add [`agent-instructions.md`](../src/zotero_setup/templates/agent-instructions.md) to the project's `CLAUDE.md` / `AGENTS.md` so the assistant knows the workflow.

## Claude Desktop

`zotero-mcp setup` configures Claude Desktop automatically (local mode). For the group: `zotero-mcp setup --no-local --api-key <KEY> --library-id <GROUP_ID>`, then add `ZOTERO_LIBRARY_TYPE=group` to the `env` block in `claude_desktop_config.json`. That file lives in your user profile – never copy it into a repo.

## Other clients (Cursor, VS Code, Continue, …)

Same pattern: command `zotero-mcp`, environment variables as above. Always pass secrets via environment variables / a secret store, never as plain text in committed config files.

## Security with AI assistants

- Use a **read-only key** for pure research; a write key only if the assistant should create/annotate items.
- Let the assistant confirm write tools (Claude Code asks by default).
- Never paste the key into a chat – it would end up in histories/transcripts.
- More server options: https://github.com/54yyyu/zotero-mcp/blob/main/docs/configuration.md
