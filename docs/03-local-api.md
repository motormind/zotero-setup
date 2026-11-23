# 3. Local API (Zotero desktop)

Zotero 7+ serves the Web API endpoints locally – great for working on your own machine and for AI assistants.

## Enable

Zotero → *Settings → Advanced* → **"Allow other applications on this computer to communicate with Zotero"**

## Usage

```bash
# the user ID is always 0 locally
curl -s "http://localhost:23119/api/users/0/items/top?limit=5" | jq '.[].data.title'
curl -s "http://localhost:23119/api/users/0/items/top?q=transformer&format=bibtex"
# groups: /api/groups/<groupID>/...
```

| | Web API | Local API |
|---|---|---|
| key required | yes (except public libraries) | reading: **no**; writing (Zotero 10+): a local key granted at runtime |
| rate limit | yes | no |
| max `limit` | 100 | none |
| `format=atom` | yes | no (501) |
| `q` search | server search | local quick search (results may differ) |
| versions | server versions | from Zotero 10 on, independent of Web API versions → cache separately |
| reachable from CI | yes | no (local only, only while Zotero runs) |

A local `403` usually means the setting above is not enabled.

`zt` can read locally too: `ZOTERO_LOCAL=true zt search …` / `zt pull` (writes via `zt push` always use the Web API).

> Note for dev containers / Codespaces: `localhost` inside the container is **not** the machine Zotero runs on. Use the Web API there.
