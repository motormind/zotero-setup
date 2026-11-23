"""zt - sync papers between a research repo and a Zotero (group) library."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .api import Zotero, ZoteroError
from .config import CONFIG_NAME, ConfigError, Config, load_config
from .sources import (
    Candidate, fit_to_template, from_arxiv, from_bibtex_entry, from_doi, item_identity,
    norm_title, parse_bibtex, parse_identifier, read_ids_file,
)


def client(cfg: Config, need_key: bool = True) -> Zotero:
    cfg.require_library()
    if need_key:
        cfg.require_key()
    base = os.environ.get("ZOTERO_API_URL", "").rstrip("/") or None  # e.g. self-hosted server
    return Zotero(cfg.prefix, cfg.api_key, cfg.local, base=None if cfg.local else base)


def _resolve_globs(root: Path, patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        out.extend(sorted(p for p in root.glob(pat) if p.is_file()))
    return out


# ------------------------------------------------------------------------- init
def cmd_init(cfg: Config, args) -> int:
    root = cfg.root
    tpl = resources.files("zotero_setup") / "templates"

    def write(name: str, dest: str):
        target = root / dest
        if target.exists():
            print(f"  skip   {dest} (exists)")
            return
        content = (tpl / name).read_text(encoding="utf-8")
        if name == "zotero.toml" and args.library_id:
            content = re.sub(r'^(library_id\s*=\s*)"[^"]*"', rf'\g<1>"{args.library_id}"', content, flags=re.M)
        target.write_text(content, encoding="utf-8")
        print(f"  create {dest}")

    write("zotero.toml", CONFIG_NAME)
    write("env.example", ".env.example")
    if args.mcp:
        write("mcp.json", ".mcp.json")

    gi = root / ".gitignore"
    snippet = (tpl / "gitignore-snippet").read_text(encoding="utf-8")
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    missing = [ln for ln in snippet.splitlines() if ln and not ln.startswith("#") and ln not in existing]
    if missing:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if existing and not existing.endswith("\n") else "") + "\n" + snippet)
        print("  update .gitignore")

    print("\nNext steps:\n"
          "  1. cp .env.example .env   and put your ZOTERO_API_KEY there (never commit .env)\n"
          f"  2. edit {CONFIG_NAME} (library_id, collection, push sources)\n"
          "  3. zt whoami   ->  zt collections   ->  zt pull / zt push --dry-run")
    if args.mcp:
        print("  4. MCP: install `zotero-mcp-server`, see docs/04-mcp.md")
    return 0


# ---------------------------------------------------------------------- reading
def cmd_whoami(cfg: Config, args) -> int:
    z = client(cfg, need_key=not cfg.local)
    if cfg.local:
        print("mode: local API (Zotero desktop, no key)")
    else:
        info = z.key_info()
        print(f"key owner : {info.get('username')} (userID {info.get('userID')})")
        access = info.get("access", {})
        if "user" in access:
            print(f"personal  : {access['user']}")
        groups = access.get("groups", {})
        for gid, perms in groups.items():
            print(f"group {gid:<8}: {perms}")
    _, rh, _ = z.request("GET", "items/top", {"limit": 1, "format": "keys"})
    print(f"library   : {cfg.prefix}  ->  {rh.get('total-results', '?')} top-level items, "
          f"version {rh.get('last-modified-version', '?')}")
    if cfg.collection:
        c = z.get_json(f"collections/{cfg.collection}")
        print(f"collection: {cfg.collection} = \"{c['data']['name']}\" ({c['meta'].get('numItems', '?')} items)")
    return 0


def cmd_collections(cfg: Config, args) -> int:
    z = client(cfg, need_key=not cfg.local)
    cols = z.collections()
    by_key = {c["key"]: c for c in cols}

    def path(c):
        parts = [c["data"]["name"]]
        parent = c["data"].get("parentCollection")
        while parent and parent in by_key:
            parts.insert(0, by_key[parent]["data"]["name"])
            parent = by_key[parent]["data"].get("parentCollection")
        return " / ".join(parts)

    for c in sorted(cols, key=path):
        print(f"{c['key']}  {c['meta'].get('numItems', 0):>5}  {path(c)}")
    return 0


def _fmt_item(d: dict) -> str:
    creators = d.get("creators") or []
    first = (creators[0].get("lastName") or creators[0].get("name", "")) if creators else ""
    if len(creators) > 1:
        first += " et al."
    year = (re.search(r"\d{4}", d.get("date", "")) or [""])[0]
    return f"{d.get('key')}  {year:4}  {first[:25]:25}  {d.get('title', '')[:90]}"


def cmd_search(cfg: Config, args) -> int:
    z = client(cfg, need_key=not cfg.local)
    path = f"collections/{cfg.collection}/items/top" if args.in_collection and cfg.collection else "items/top"
    params = {"q": " ".join(args.query), "qmode": "everything", "limit": args.limit}
    if args.format:
        params["format"] = args.format
        _, _, data = z.request("GET", path, params)
        print(data.decode("utf-8"))
        return 0
    for it in z.get_json(path, params):
        print(_fmt_item(it["data"]))
    return 0


def cmd_pull(cfg: Config, args) -> int:
    z = client(cfg, need_key=not cfg.local)
    fmt = args.format or cfg.bib_format
    out = Path(args.output or cfg.bib_output)
    if not out.is_absolute():
        out = cfg.root / out
    if not cfg.collection:
        print("note: no collection configured -> exporting the whole library", file=sys.stderr)
    text = z.export(fmt, cfg.collection)
    comment = "%" if fmt in {"bibtex", "biblatex"} else None
    if comment:
        src = f"collection {cfg.collection}" if cfg.collection else "library"
        text = f"{comment} Generated by `zt pull` from Zotero {cfg.prefix} ({src}). Do not edit by hand.\n\n" + text
    if args.stdout:
        sys.stdout.write(text)
        return 0
    old = out.read_text(encoding="utf-8") if out.exists() else None
    if old == text:
        print(f"{out.relative_to(cfg.root)} is up to date")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    n = len(re.findall(r"^@", text, re.M)) if comment else "?"
    print(f"wrote {out.relative_to(cfg.root)} ({n} entries, format {fmt})")
    return 0


# ---------------------------------------------------------------------- pushing
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _pdf_keys(c: Candidate | dict) -> set[str]:
    """Filename stems a PDF may have to be matched to this item."""
    ids = c if isinstance(c, dict) else {"doi": c.doi, "arxiv": c.arxiv, "citekey": c.citekey}
    return {_slug(v) for k, v in ids.items() if v and k in {"doi", "arxiv", "citekey"}}


def collect_candidates(cfg: Config, extra_ids: list[str], verbose: bool) -> list[Candidate]:
    cands: list[Candidate] = []
    raw_ids: list[tuple[str, str, str]] = []
    for f in _resolve_globs(cfg.root, cfg.ids_files):
        raw_ids.extend((k, i, src.replace(str(f), str(f.relative_to(cfg.root))))
                       for k, i, src in read_ids_file(f))
    for s in extra_ids:
        kind, ident = parse_identifier(s)
        raw_ids.append((kind, ident, "cli"))

    for kind, ident, src in raw_ids:
        c = Candidate(source=src)
        try:
            if kind == "doi":
                c.doi = ident
                c.item = from_doi(ident)
            elif kind == "arxiv":
                c.arxiv = ident.lower()
                c.item = from_arxiv(ident)
            else:
                c.error = f"not a DOI or arXiv ID: {ident!r}"
        except Exception as e:  # network / lookup errors are reported per item
            c.error = f"lookup failed for {ident}: {e}"
        if verbose and c.item:
            print(f"  resolved {ident} -> {c.item.get('title', '')[:70]}")
        cands.append(c)

    for f in _resolve_globs(cfg.root, cfg.bib_files):
        for e in parse_bibtex(f.read_text(encoding="utf-8")):
            item = from_bibtex_entry(e)
            c = Candidate(source=f"{f.relative_to(cfg.root)}:{e['_key']}", item=item, citekey=e["_key"],
                          doi=item.get("DOI", ""))
            m = re.search(r"arXiv:(\S+)", item.get("archiveID", ""))
            c.arxiv = m.group(1).lower() if m else ""
            cands.append(c)
    return cands


def library_index(z: Zotero) -> tuple[dict[tuple[str, str], dict], list[dict]]:
    idx: dict[tuple[str, str], dict] = {}
    items = list(z.iter_json("items/top", {"format": "json"}))
    for it in items:
        for k, v in item_identity(it["data"]).items():
            idx.setdefault((k, v), it)
    return idx, items


def find_existing(idx, c: Candidate) -> dict | None:
    probes = [("doi", c.doi.lower()), ("arxiv", c.arxiv), ("citekey", c.citekey)]
    if c.item:
        probes.append(("title", norm_title(c.item.get("title", ""))))
    for k, v in probes:
        if v and (k, v) in idx:
            return idx[(k, v)]
    return None


def cmd_push(cfg: Config, args) -> int:
    z = client(cfg)
    if cfg.local:
        raise ConfigError("push needs the Web API. Unset ZOTERO_LOCAL for this command.")
    dry = args.dry_run
    tags = cfg.tags + (args.tag or [])
    print("collecting sources ...")
    cands = collect_candidates(cfg, args.ids or [], args.verbose)
    pdfs = _resolve_globs(cfg.root, [f"{d.rstrip('/')}/**/*.pdf" for d in cfg.pdf_dirs]) if (
        cfg.upload_pdfs or args.pdfs) else []

    print("reading library index ...")
    idx, _ = library_index(z)

    failures = 0
    to_create: list[tuple[Candidate, dict]] = []
    seen: set[str] = set()
    pdf_targets: dict[str, str] = {}  # pdf slug -> zotero item key
    for c in cands:
        if c.error:
            print(f"  ERROR  {c.source}: {c.error}")
            failures += 1
            continue
        existing = find_existing(idx, c)
        if existing:
            for s in _pdf_keys(c):
                pdf_targets[s] = existing["key"]
            cols = existing["data"].get("collections", [])
            if cfg.collection and cfg.collection not in cols:
                print(f"  LINK   {c.source}: exists ({existing['key']}) -> add to collection")
                if not dry:
                    z.request("PATCH", f"items/{existing['key']}",
                              body=json.dumps({"collections": cols + [cfg.collection]}).encode(),
                              headers={"Content-Type": "application/json",
                                       "If-Unmodified-Since-Version": str(existing["version"])})
            elif args.verbose:
                print(f"  skip   {c.source}: already in Zotero ({existing['key']})")
            continue
        dedup_key = c.doi.lower() or c.arxiv or norm_title(c.item.get("title", ""))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        item = fit_to_template(c.item, z.template(c.item["itemType"]), tags, cfg.collection)
        to_create.append((c, item))
        print(f"  NEW    {c.source}: [{item['itemType']}] {item.get('title', '')[:80]}")

    if dry:
        for c, _ in to_create:
            for s in _pdf_keys(c):
                pdf_targets[s] = "(new item)"
    if to_create and not dry:
        results = z.create_items([it for _, it in to_create])
        for (c, _), (_, key, err) in zip(to_create, results):
            if err:
                print(f"  FAILED {c.source}: {err}")
                failures += 1
            else:
                for s in _pdf_keys(c):
                    pdf_targets[s] = key

    if pdfs:
        # existing library items can also receive PDFs (matched by citekey / DOI / arXiv slug)
        for (k, v), it in idx.items():
            if k in {"doi", "arxiv", "citekey"}:
                pdf_targets.setdefault(_slug(v), it["key"])
        child_cache: dict[str, set[str]] = {}
        existing_keys = {it["key"] for it in idx.values()}
        for pdf in pdfs:
            rel = pdf.relative_to(cfg.root)
            parent = pdf_targets.get(_slug(pdf.stem))
            if not parent and not args.standalone_pdfs:
                print(f"  ?      {rel}: no matching item (name it <citekey>.pdf or <doi>.pdf, "
                      "or use --standalone-pdfs)")
                continue
            if parent:
                if parent not in child_cache:
                    is_new = parent not in existing_keys  # created just now -> no children yet
                    child_cache[parent] = set() if is_new else {
                        ch["data"].get("filename") for ch in z.children(parent)}
                if pdf.name in child_cache[parent]:
                    if args.verbose:
                        print(f"  skip   {rel}: already attached to {parent}")
                    continue
                child_cache[parent].add(pdf.name)
            print(f"  PDF    {rel} -> {parent or '(standalone)'}")
            if not dry:
                try:
                    z.upload_pdf(pdf, parent, collection=None if parent else cfg.collection)
                except ZoteroError as e:
                    print(f"  FAILED {rel}: {e}")
                    failures += 1

    created = len(to_create)
    print(f"\n{'[dry-run] would create' if dry else 'created'} {created} item(s); {failures} error(s).")
    if dry and created:
        print("Run again without --dry-run to write to Zotero.")
    return 1 if failures else 0


# ------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zt", description=__doc__)
    p.add_argument("--version", action="version", version=f"zt {__version__}")
    p.add_argument("-C", "--project", type=Path, help="project root (default: auto-detect)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help=f"create {CONFIG_NAME}, .env.example, .gitignore entries")
    s.add_argument("--library-id", help="Zotero group/user ID")
    s.add_argument("--mcp", action="store_true", help="also create a project .mcp.json for Claude Code")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("whoami", help="show key permissions and check library access")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("collections", help="list collections with their keys")
    s.set_defaults(func=cmd_collections)

    s = sub.add_parser("search", help="search the library")
    s.add_argument("query", nargs="+")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--format", help="e.g. bibtex, biblatex, csljson, ris, bib")
    s.add_argument("--in-collection", action="store_true", help="only the configured collection")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("pull", help="export the collection to a bibliography file in the repo")
    s.add_argument("-o", "--output")
    s.add_argument("-f", "--format", help="biblatex (default), bibtex, csljson, ris, ...")
    s.add_argument("--stdout", action="store_true")
    s.set_defaults(func=cmd_pull)

    s = sub.add_parser("push", help="add papers from the repo (DOIs, arXiv IDs, .bib, PDFs) to Zotero")
    s.add_argument("ids", nargs="*", help="extra DOIs / arXiv IDs / URLs")
    s.add_argument("-n", "--dry-run", action="store_true")
    s.add_argument("--pdfs", action="store_true", help="upload PDFs from pdf_dirs (overrides upload_pdfs)")
    s.add_argument("--standalone-pdfs", action="store_true", help="upload unmatched PDFs as standalone attachments")
    s.add_argument("-t", "--tag", action="append", help="extra tag for new items (repeatable)")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_push)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.project.resolve() if args.project else None)
        return args.func(cfg, args)
    except (ConfigError, ZoteroError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
