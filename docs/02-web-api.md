# 2. Web API v3 – cheat sheet

Official docs: https://www.zotero.org/support/dev/web_api/v3/basics

## Basics

```
Base URL:  https://api.zotero.org
Headers:   Zotero-API-Version: 3
           Zotero-API-Key: <key>          (alternative: Authorization: Bearer <key>)
Prefix:    /users/<userID>   or   /groups/<groupID>
```

Always send the key as a **header**, not as `?key=` – otherwise it ends up in logs and in `Link` URLs.

## Reading

| Endpoint | Content |
|---|---|
| `GET {prefix}/items` | all items (incl. attachments/notes) |
| `GET {prefix}/items/top` | top-level items only (usually what you want) |
| `GET {prefix}/items/<itemKey>` | single item |
| `GET {prefix}/items/<itemKey>/children` | attachments + notes of an item |
| `GET {prefix}/items/trash` | trash |
| `GET {prefix}/collections` / `collections/top` | collections |
| `GET {prefix}/collections/<key>/items/top` | items of a collection |
| `GET {prefix}/searches` | saved searches (definition only, no results) |
| `GET {prefix}/tags` | tags |
| `GET /keys/<key>` | permissions + userID of a key |
| `GET /users/<userID>/groups` | groups of a user |
| `GET /itemTypes`, `/itemFields`, `/items/new?itemType=journalArticle` | schema / templates (no auth) |

## Important parameters

| Parameter | Values |
|---|---|
| `q` | search term |
| `qmode` | `titleCreatorYear` (default) · `everything` (incl. full text) |
| `tag` | `tag=foo` · `tag=foo \|\| bar` (OR) · `tag=-foo` (NOT) · repeated = AND |
| `itemType` | `journalArticle`, `-attachment`, `book \|\| bookSection` |
| `itemKey` | up to 50 keys, comma-separated |
| `sort` / `direction` | `dateModified` (default), `dateAdded`, `title`, `date`, `creator` … / `asc`, `desc` |
| `limit` / `start` | 1–100 (default 25) / offset |
| `since` | only objects modified after library version N |
| `format` | `json` (default), `keys`, `versions`, `bib`, `bibtex`, `biblatex`, `csljson`, `ris`, `atom`, … |
| `include` | `data`, `bib`, `citation`, export formats (comma-separated) |
| `style` / `locale` | CSL style, e.g. `apa`, `ieee` / `en-US`, `de-DE` |

Examples:

```bash
# top-level items matching "LLM" in title/creator/year, newest first
GET /groups/123/items/top?q=LLM&sort=dateAdded&direction=desc&limit=50

# formatted bibliography (APA)
GET /groups/123/collections/ABCD1234/items/top?format=bib&style=apa

# BibLaTeX export of a collection
GET /groups/123/collections/ABCD1234/items/top?format=biblatex&limit=100
```

## Pagination

- response header `Total-Results` = total count
- header `Link` contains `rel="next"` → follow it until there is no `next`
- max 100 per page

## Versions, caching & sync

- Every response carries `Last-Modified-Version` (library version).
- Conditional GET: `If-Modified-Since-Version: <v>` → `304 Not Modified` if nothing changed.
- Incremental sync:
  1. `GET {prefix}/items?since=<lastVersion>&format=versions` → `{itemKey: version}` of changed items
  2. fetch changed items in chunks of 50 via `?itemKey=K1,K2,...`
  3. `GET {prefix}/deleted?since=<lastVersion>` → deleted keys
  4. store the new `Last-Modified-Version`

Details: https://www.zotero.org/support/dev/web_api/v3/syncing

## Writing

Docs: https://www.zotero.org/support/dev/web_api/v3/write_requests

```bash
# 1. get a template
GET /items/new?itemType=journalArticle
# 2. fill in fields, up to 50 objects per request
POST {prefix}/items
Content-Type: application/json
Zotero-Write-Token: <32 random hex chars>    # prevents duplicates on retry
[ {...item1...}, {...item2...} ]
```

- The response lists `successful`, `unchanged`, `failed` per index → **always check `failed`**, even on HTTP 200.
- Update a single item: `PATCH {prefix}/items/<key>` with `If-Unmodified-Since-Version: <item.version>` (or `version` in the body).
- Delete: `DELETE {prefix}/items?itemKey=A,B,C` with `If-Unmodified-Since-Version: <libraryVersion>`.
- `412 Precondition Failed` = someone else changed it in the meantime → reload, merge, retry.
- File uploads (PDFs) are a multi-step process (authorize → upload → register), see https://www.zotero.org/support/dev/web_api/v3/file_upload – implemented in `zt` (`Zotero.upload_pdf`).

## Rate limits & errors

| Status / header | Meaning | Reaction |
|---|---|---|
| `Backoff: N` | server under load | only do what's necessary, then pause N seconds |
| `429` + `Retry-After: N` | too many requests | wait at least N seconds (otherwise exponential backoff) |
| `503` + `Retry-After` | maintenance/overload | same as 429 |
| `403` | key missing/wrong/no permission | check key permissions (`zt whoami`) |
| `404` | wrong ID/key or library not visible | check user vs group prefix |
| `412` / `428` | version conflict / write token or version missing | reload or set the header |

- At most **4 concurrent** requests.
- Batch writes (50 per request) instead of single requests.
- `since=` + a local cache instead of full re-downloads.

Reference implementation of pagination, backoff, batched writes and file upload: [`src/zotero_setup/api.py`](../src/zotero_setup/api.py).
