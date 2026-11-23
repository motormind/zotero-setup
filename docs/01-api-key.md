# 1. Create an API key

Required for the **Web API** (and for MCP writes on older Zotero versions). For read-only access through the local API (Zotero desktop running) you need **no** key → [03-local-api.md](03-local-api.md).

## Steps

1. https://www.zotero.org/settings/keys → **Create new private key**
2. Use a descriptive name, e.g. `project-xyz-readonly-ci`
3. Choose **minimal** permissions:

| Purpose | Personal library | Groups |
|---|---|---|
| reading in scripts/CI | ❌ off | *Per group permissions* → only the project group → **Read only** |
| AI assistant, read-only | ❌ off | project group → read only |
| `zt push` / annotating | only if needed | project group → **Read/Write** |
| reading notes | enable "Allow notes access" only if really needed | – |

4. Copy the key once and put it into the project's local `.env` (template: `zt init` or [`env.example`](../src/zotero_setup/templates/env.example)).

## Finding IDs

- **User ID**: shown on https://www.zotero.org/settings/keys ("Your userID for use in API calls is …")
- **Group ID**: open the group on zotero.org → number in the URL `zotero.org/groups/<groupID>/...`
- Or via the API (or simply `zt whoami`):
  ```bash
  curl -s -H "Zotero-API-Key: $ZOTERO_API_KEY" https://api.zotero.org/keys/$ZOTERO_API_KEY
  # → userID, username, access (which libraries, which permissions)
  curl -s -H "Zotero-API-Key: $ZOTERO_API_KEY" https://api.zotero.org/users/<userID>/groups
  ```

## Where to store it

| Where | How |
|---|---|
| locally | `.env` in the project (git-ignored!) or a password-manager CLI (`op run`, `pass`, …) |
| GitHub Actions | *Settings → Secrets and variables → Actions* → `ZOTERO_API_KEY` |
| Codespaces / dev containers | *Codespaces secrets* instead of files |

Never: in code, as plain text in `.mcp.json`, in READMEs/issues, or in prompts/chats with AI assistants.

## Rotation

- One key per project/person/purpose → can be revoked individually.
- Delete keys when people leave or a project ends.
