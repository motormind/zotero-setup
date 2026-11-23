# zotero-setup

A shared tool and guide that lets **any research repo** work with a **Zotero group library**:

- **`zt push`** – send papers from the repo (DOIs, arXiv IDs, `.bib` files, PDFs) to the Zotero group, with duplicate detection
- **`zt pull`** – export the project's collection into the repo as `references.bib` (or CSL-JSON, RIS)
- **`zt search` / `zt collections` / `zt whoami`** – look things up and check access
- **Zotero MCP** – lets AI assistants (Claude Code, Claude Desktop, Cursor, …) search, cite and annotate the library

Python ≥ 3.11 standard library only, no dependencies. Talks to the [Zotero Web API v3](https://www.zotero.org/support/dev/web_api/v3/start).

> This repo is public and contains **no** keys, `.env` files, library IDs or AI-tool data – only placeholders. See [SECURITY.md](SECURITY.md).

## Quick start in your project

```bash
# 1. install once per machine
uv tool install git+https://github.com/motormind/zotero-setup     # or: pipx install git+https://github.com/motormind/zotero-setup

# 2. inside your project repo
cd my-project
zt init --library-id <GROUP_ID>      # creates .zotero.toml, .env.example, .gitignore entries (--mcp: also .mcp.json)
cp .env.example .env                 # put your ZOTERO_API_KEY there -> .env is NEVER committed
zt whoami                            # check permissions and access to the group
zt collections                       # find the collection key -> put it into .zotero.toml

# 3. work
echo "10.1038/nature14539" >> papers/ids.txt
echo "arXiv:1706.03762"    >> papers/ids.txt
zt push --dry-run                    # shows what would be created
zt push                              # creates items, adds them to the collection, tags them
zt pull                              # writes references.bib
```

The group ID is part of the group URL: `zotero.org/groups/<GROUP_ID>/<name>`. API key: [docs/01-api-key.md](docs/01-api-key.md).

Other ways to install (submodule, dev dependency): [docs/05-project-integration.md](docs/05-project-integration.md).

## What `zt push` does

| Source (in `.zotero.toml`) | Processing |
|---|---|
| `ids_files` – lines with a DOI, `doi.org` URL, `arXiv:` ID or arXiv URL | metadata via Crossref / arXiv API → matching Zotero item type |
| `bib_files` – BibTeX/BibLaTeX | entries are imported as-is; the citekey is stored as `Citation Key:` in *Extra* (Better BibTeX compatible) |
| `pdf_dirs` + `upload_pdfs = true` (or `--pdfs`) | a PDF is attached to the matching item if it is named `<citekey>.pdf`, `<doi>.pdf` or `<arxiv-id>.pdf`; otherwise, with `--standalone-pdfs`, uploaded as a standalone item |

- **Duplicates** are detected across the whole library by DOI, arXiv ID, citekey and normalized title. If a paper already exists, it is only added to the collection.
- New items get the configured `collection` and `tags`.
- Writes in batches of 50 with write tokens and version checks; honors `Backoff` / `Retry-After`.
- PDFs count against the group owner's storage quota → off by default.

## Contents

| Path | Purpose |
|---|---|
| [src/zotero_setup/](src/zotero_setup/) | the `zt` CLI (`api.py` = Web API client, `sources.py` = DOI/arXiv/BibTeX, `cli.py`) |
| [src/zotero_setup/templates/](src/zotero_setup/templates/) | templates: `.zotero.toml`, `.env.example`, `.mcp.json`, `.gitignore` snippet, agent instructions |
| [docs/01-api-key.md](docs/01-api-key.md) | create a least-privilege API key and store it safely |
| [docs/02-web-api.md](docs/02-web-api.md) | Web API v3 cheat sheet: endpoints, parameters, pagination, sync, writes, rate limits |
| [docs/03-local-api.md](docs/03-local-api.md) | local API of Zotero desktop |
| [docs/04-mcp.md](docs/04-mcp.md) | Zotero MCP for Claude Code / Claude Desktop / other clients |
| [docs/05-project-integration.md](docs/05-project-integration.md) | using it in projects: layout, CI, LaTeX/Quarto/Pandoc |
| [examples/curl/zotero.sh](examples/curl/zotero.sh) | plain curl examples |

## Ground rules

1. **Keys only in a local `.env` or a secret store** (GitHub Secrets, 1Password, …) – never in code, commits, `.zotero.toml`, issues or chats. `zt` refuses keys in `.zotero.toml`.
2. **Least privilege**: one key per person/purpose, only the project group, read-only for CI.
3. **One collection per project** inside the group – keeps `references.bib` focused.
4. **`references.bib` is generated** – change things in Zotero, then `zt pull`.
5. **`--dry-run` first**, then write.

## Development

```bash
python3 -m unittest discover -s tests     # offline tests
pre-commit install                        # secret scan before every commit
python3 zt.py --help                      # run without installing
```

## License

MIT – see [LICENSE](LICENSE).
