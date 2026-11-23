# Security

This repo is public and must contain **placeholders only**.

## Never commit

- Zotero API keys, OAuth tokens, `.env` files
- AI-tool configuration and data: `.claude/`, `~/.claude.json`, `CLAUDE.local.md`, `claude_desktop_config.json`, chat logs, transcripts
- library exports (`.bib`, `.ris`, `zotero.sqlite`, PDFs)

## Safeguards in this repo

- `.gitignore` blocks the paths above
- `pre-commit` with [gitleaks](https://github.com/gitleaks/gitleaks) (plus a custom Zotero key rule in `.gitleaks.toml`)
- the `secret-scan` GitHub Action checks every push and PR

```bash
pipx install pre-commit
pre-commit install          # runs on every commit from now on
pre-commit run --all-files  # check everything once
```

## Leaked a key?

1. Delete it immediately at https://www.zotero.org/settings/keys (or `DELETE /keys/<key>`).
2. Create a new key with minimal permissions.
3. Clean the history (e.g. `git filter-repo`) – this does **not** replace step 1.

Please report security issues privately to the maintainers, not as a public issue.
