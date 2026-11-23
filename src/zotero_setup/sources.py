"""Turn things found in a repo (DOIs, arXiv IDs, BibTeX) into Zotero item dicts.

An item is produced as a loose dict {"itemType": ..., "creators": [...], <field>: ...};
`fit_to_template` later drops every field the Zotero schema does not know for that type.
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

UA = "zotero-setup/0.1 (research reference sync)"
if os.environ.get("CROSSREF_MAILTO"):  # optional, Crossref "polite pool"; set it yourself if you want
    UA += f" mailto:{os.environ['CROSSREF_MAILTO']}"

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.I)
ARXIV_RE = re.compile(
    r"(?:arxiv[:/ ]|arxiv\.org/(?:abs|pdf)/)\s*(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?",
    re.I,
)
BARE_ARXIV_RE = re.compile(r"^(\d{4}\.\d{4,5})(v\d+)?$")


@dataclass
class Candidate:
    """Something we want in Zotero."""
    source: str                 # where it came from (file:line or citekey)
    item: dict | None = None    # Zotero item data (None if lookup failed)
    doi: str = ""
    arxiv: str = ""
    citekey: str = ""
    error: str = ""
    pdfs: list = field(default_factory=list)


# --------------------------------------------------------------------------- ids
def normalize_doi(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", s, flags=re.I)
    return s.rstrip(".,;").lower()


def parse_identifier(line: str) -> tuple[str, str]:
    """Return ('doi'|'arxiv'|'', id)."""
    line = line.strip()
    m = ARXIV_RE.search(line) or BARE_ARXIV_RE.match(line)
    if m:
        return "arxiv", m.group(1)
    m = DOI_RE.search(line)
    if m:
        doi = normalize_doi(m.group(1))
        am = re.match(r"10\.48550/arxiv\.(.+)", doi)
        if am:
            return "arxiv", am.group(1)
        return "doi", doi
    return "", line


def read_ids_file(path) -> list[tuple[str, str, str]]:
    """Lines of DOIs / arXiv IDs / URLs. '#' starts a comment. Returns (kind, id, source)."""
    out = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for n, raw in enumerate(lines, 1):
        line = re.split(r"(?:^|\s)#", raw, maxsplit=1)[0].strip()  # '#' inside a URL is kept
        if not line:
            continue
        kind, ident = parse_identifier(line)
        out.append((kind, ident, f"{path}:{n}"))
    return out


def _get(url: str, accept: str = "application/json") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


# ----------------------------------------------------------------------- crossref
CROSSREF_TYPES = {
    "journal-article": ("journalArticle", "publicationTitle"),
    "proceedings-article": ("conferencePaper", "proceedingsTitle"),
    "book-chapter": ("bookSection", "bookTitle"),
    "book": ("book", None),
    "monograph": ("book", None),
    "edited-book": ("book", None),
    "posted-content": ("preprint", "repository"),
    "report": ("report", None),
    "dissertation": ("thesis", None),
    "dataset": ("dataset", "repository"),
}


def _strip_jats(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


CSL_TYPES = {
    "article-journal": ("journalArticle", "publicationTitle"),
    "paper-conference": ("conferencePaper", "proceedingsTitle"),
    "chapter": ("bookSection", "bookTitle"),
    "book": ("book", None),
    "article": ("preprint", None),
    "report": ("report", None),
    "thesis": ("thesis", None),
    "dataset": ("dataset", None),
    "software": ("computerProgram", None),
}


def from_doi_csl(doi: str) -> dict:
    """Any DOI registrar (DataCite: Zenodo, figshare, ...) via doi.org content negotiation."""
    msg = json.loads(_get("https://doi.org/" + urllib.parse.quote(doi),
                          accept="application/vnd.citationstyles.csl+json"))
    item_type, container_field = CSL_TYPES.get(msg.get("type", ""), ("document", None))
    ctype = "programmer" if item_type == "computerProgram" else "author"
    creators = []
    for a in msg.get("author", []):
        if a.get("family"):
            creators.append({"creatorType": ctype, "lastName": a["family"], "firstName": a.get("given", "")})
        elif a.get("literal") or a.get("name"):
            creators.append({"creatorType": ctype, "name": a.get("literal") or a["name"]})
    parts = ((msg.get("issued") or {}).get("date-parts") or [[]])[0]
    title = msg.get("title") or ""
    publisher = msg.get("publisher", "")
    item = {
        "itemType": item_type,
        "title": " ".join(title) if isinstance(title, list) else title,
        "creators": creators,
        "date": "-".join(f"{int(p):02d}" if i else str(p) for i, p in enumerate(parts) if p),
        "DOI": msg.get("DOI", doi),
        "url": msg.get("URL", f"https://doi.org/{doi}"),
        "volume": str(msg.get("volume", "")),
        "issue": str(msg.get("issue", "")),
        "pages": msg.get("page", ""),
        "publisher": publisher,
        "company": publisher,
        "repository": publisher,
        "versionNumber": str(msg.get("version", "")),
        "abstractNote": _strip_jats(msg.get("abstract", "")),
        "language": msg.get("language", ""),
        "_extra": [f"DOI: {msg.get('DOI', doi)}"],
    }
    container = msg.get("container-title") or ""
    if container_field and container:
        item[container_field] = container if isinstance(container, str) else container[0]
    return item


def from_doi(doi: str) -> dict:
    try:
        raw = _get("https://api.crossref.org/works/" + urllib.parse.quote(doi))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return from_doi_csl(doi)  # not a Crossref DOI
    msg = json.loads(raw)["message"]
    item_type, container_field = CROSSREF_TYPES.get(msg.get("type", ""), ("journalArticle", "publicationTitle"))
    creators = []
    for role, ctype in (("author", "author"), ("editor", "editor")):
        for a in msg.get(role, []):
            if "family" in a:
                creators.append({"creatorType": ctype, "lastName": a["family"], "firstName": a.get("given", "")})
            elif "name" in a:
                creators.append({"creatorType": ctype, "name": a["name"]})
    date_parts = (msg.get("published") or msg.get("issued") or {}).get("date-parts", [[None]])[0]
    date = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(date_parts) if p)
    item = {
        "itemType": item_type,
        "title": " ".join(msg.get("title") or [""]),
        "creators": creators,
        "date": date,
        "DOI": msg.get("DOI", doi),
        "url": msg.get("URL", f"https://doi.org/{doi}"),
        "volume": msg.get("volume", ""),
        "issue": msg.get("issue", ""),
        "pages": msg.get("page", ""),
        "publisher": msg.get("publisher", ""),
        "ISSN": ", ".join(msg.get("ISSN", [])),
        "ISBN": ", ".join(msg.get("ISBN", [])),
        "abstractNote": _strip_jats(msg.get("abstract", "")),
        "language": msg.get("language", ""),
    }
    container = (msg.get("container-title") or [""])[0]
    if container_field and container:
        item[container_field] = container
    short = (msg.get("short-container-title") or [""])[0]
    if short:
        item["journalAbbreviation"] = short
    if item_type == "preprint" and not item.get("repository"):
        item["repository"] = msg.get("publisher", "")
    # DOI is not a field of every item type (e.g. bookSection) -> keep it in Extra
    item["_extra"] = [f"DOI: {item['DOI']}"]
    return item


# -------------------------------------------------------------------------- arXiv
ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def from_arxiv(arxiv_id: str) -> dict:
    data = _get("https://export.arxiv.org/api/query?" + urllib.parse.urlencode({"id_list": arxiv_id}),
                accept="application/atom+xml")
    entry = ET.fromstring(data).find("a:entry", ATOM)
    if entry is None or entry.find("a:title", ATOM) is None:
        raise LookupError(f"arXiv:{arxiv_id} not found")
    text = lambda tag: re.sub(r"\s+", " ", (entry.findtext(tag, "", ATOM) or "")).strip()  # noqa: E731
    creators = []
    for a in entry.findall("a:author", ATOM):
        name = (a.findtext("a:name", "", ATOM) or "").strip()
        first, _, last = name.rpartition(" ")
        creators.append({"creatorType": "author", "firstName": first, "lastName": last} if first
                        else {"creatorType": "author", "name": name})
    doi = text("arxiv:doi")
    return {
        "itemType": "preprint",
        "title": text("a:title"),
        "creators": creators,
        "abstractNote": text("a:summary"),
        "date": text("a:published")[:10],
        "repository": "arXiv",
        "archiveID": f"arXiv:{arxiv_id}",
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "DOI": f"10.48550/arXiv.{arxiv_id}",
        "_extra": [f"Published DOI: {doi}"] if doi else [],
    }


# ------------------------------------------------------------------------- BibTeX
BIB_TYPES = {
    "article": ("journalArticle", "publicationTitle"),
    "inproceedings": ("conferencePaper", "proceedingsTitle"),
    "conference": ("conferencePaper", "proceedingsTitle"),
    "book": ("book", None),
    "incollection": ("bookSection", "bookTitle"),
    "inbook": ("bookSection", "bookTitle"),
    "phdthesis": ("thesis", None),
    "mastersthesis": ("thesis", None),
    "thesis": ("thesis", None),
    "techreport": ("report", None),
    "report": ("report", None),
    "online": ("webpage", "websiteTitle"),
    "misc": ("document", None),
    "unpublished": ("manuscript", None),
    "dataset": ("dataset", None),
    "software": ("computerProgram", None),
}

LATEX_ACCENTS = {
    r'\"a': "ä", r'\"o': "ö", r'\"u': "ü", r'\"A': "Ä", r'\"O': "Ö", r'\"U': "Ü", r"\ss": "ß",
    r"\'e": "é", r"\'a": "á", r"\'i": "í", r"\'o": "ó", r"\'u": "ú", r"\`e": "è", r"\`a": "à",
    r"\^e": "ê", r"\^o": "ô", r"\~n": "ñ", r"\c c": "ç", r"\c{c}": "ç", r"\&": "&", r"\%": "%",
    r"\_": "_", r"\$": "$", "--": "–", "~": " ",
}


def _clean_latex(s: str) -> str:
    s = re.sub(r"\\[a-zA-Z]+\{([^{}]*)\}", r"\1", s)  # \emph{x} -> x
    for k, v in LATEX_ACCENTS.items():
        s = s.replace("{" + k + "}", v).replace(k, v)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_bibtex(text: str) -> list[dict]:
    """Small brace-aware BibTeX parser. Returns [{'_type','_key', field: value}]."""
    entries, i, n = [], 0, len(text)
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        m = re.match(r"@\s*(\w+)\s*([{(])", text[at:])
        if not m:
            i = at + 1
            continue
        etype = m.group(1).lower()
        j = at + m.end()
        # only count the delimiter that opened the entry: "a) ..." in an abstract must not close it
        opener, closer = ("{", "}") if m.group(2) == "{" else ("(", ")")
        depth, k = 1, j
        while k < n and depth:
            if text[k] == opener:
                depth += 1
            elif text[k] == closer:
                depth -= 1
            k += 1
        body, i = text[j:k - 1], k
        if etype in {"comment", "preamble", "string"}:
            continue
        key, _, rest = body.partition(",")
        entry = {"_type": etype, "_key": key.strip()}
        p = 0
        while p < len(rest):
            fm = re.match(r"\s*([\w\-:.]+)\s*=\s*", rest[p:])
            if not fm:
                break
            name = fm.group(1).lower()
            p += fm.end()
            if p < len(rest) and rest[p] == "{":
                d, q = 1, p + 1
                while q < len(rest) and d:
                    d += {"{": 1, "}": -1}.get(rest[q], 0)
                    q += 1
                val, p = rest[p + 1:q - 1], q
            elif p < len(rest) and rest[p] == '"':
                q = p + 1
                while q < len(rest) and not (rest[q] == '"' and rest[q - 1] != "\\"):
                    q += 1
                val, p = rest[p + 1:q], q + 1
            else:
                vm = re.match(r"[^,]*", rest[p:])
                val, p = vm.group(0).strip(), p + vm.end()
            entry[name] = val
            cm = re.match(r"\s*,", rest[p:])
            p += cm.end() if cm else 0
        entries.append(entry)
    return entries


def _bib_creators(value: str, ctype: str) -> list[dict]:
    out = []
    for name in re.split(r"\s+and\s+", value.strip()):
        name = name.strip()
        if not name:
            continue
        if name.startswith("{") and name.endswith("}"):  # {Organisation Name}
            out.append({"creatorType": ctype, "name": _clean_latex(name)})
            continue
        name = _clean_latex(name)
        if "," in name:
            last, first = [x.strip() for x in name.split(",", 1)]
        else:
            first, _, last = name.rpartition(" ")
        out.append({"creatorType": ctype, "lastName": last, "firstName": first} if last
                   else {"creatorType": ctype, "name": name})
    return out


MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def _month(m: str) -> str:
    m = m.strip().lower()
    if m.isdigit() and 1 <= int(m) <= 12:
        return f"{int(m):02d}"
    return f"{MONTHS.index(m[:3]) + 1:02d}" if m[:3] in MONTHS else ""


def from_bibtex_entry(e: dict) -> dict:
    etype = e["_type"]
    item_type, container_field = BIB_TYPES.get(etype, ("document", None))
    eprint = e.get("eprint", "")
    if etype in {"misc", "online", "unpublished", "article"} and (
        e.get("archiveprefix", "").lower() == "arxiv" or "arxiv" in e.get("journal", "").lower()
    ) and eprint:
        item_type, container_field = "preprint", None
    c = lambda k: _clean_latex(e.get(k, ""))  # noqa: E731
    item = {
        "itemType": item_type,
        "title": c("title"),
        "creators": _bib_creators(e.get("author", ""), "author") + _bib_creators(e.get("editor", ""), "editor"),
        "date": c("date") or "-".join(x for x in (c("year"), _month(c("month"))) if x),
        "volume": c("volume"),
        "issue": c("number") or c("issue"),
        "pages": c("pages").replace("–", "-"),
        "publisher": c("publisher"),
        "place": c("address") or c("location"),
        "DOI": normalize_doi(e["doi"]) if e.get("doi") else "",
        "url": e.get("url", "").strip(),
        "abstractNote": c("abstract"),
        "ISBN": c("isbn"),
        "ISSN": c("issn"),
        "university": c("school") or c("institution"),
        "institution": c("institution"),
        "series": c("series"),
        "edition": c("edition"),
        "language": c("language") or c("langid"),
    }
    if etype == "phdthesis":
        item["thesisType"] = "PhD thesis"
    elif etype == "mastersthesis":
        item["thesisType"] = "Master's thesis"
    container = c("journal") or c("journaltitle") or c("booktitle")
    if container_field and container:
        item[container_field] = container
    if item_type == "preprint":
        item["repository"] = "arXiv"
        item["archiveID"] = f"arXiv:{eprint}"
        item["url"] = item["url"] or f"https://arxiv.org/abs/{eprint}"
    extra = [f"Citation Key: {e['_key']}"]  # understood by Better BibTeX
    if item["DOI"]:
        extra.append(f"DOI: {item['DOI']}")
    item["_extra"] = extra
    return item


# ----------------------------------------------------------------- normalization
def fit_to_template(item: dict, template: dict, tags: list[str], collection: str) -> dict:
    """Keep only fields valid for the item type; merge Extra, tags and collection."""
    out = dict(template)
    for k, v in item.items():
        if not k.startswith("_") and k in out and v:
            out[k] = v
    out["itemType"] = item["itemType"]
    out["creators"] = item.get("creators") or []
    extra = [x for x in item.get("_extra", []) if x]
    if "DOI" in template:  # DOI has a real field -> no need to duplicate it in Extra
        extra = [x for x in extra if not x.startswith("DOI: ")]
    if extra:
        out["extra"] = "\n".join(extra)
    out["tags"] = [{"tag": t} for t in tags]
    out["collections"] = [collection] if collection else []
    out["relations"] = {}
    return out


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def item_identity(data: dict) -> dict[str, str]:
    """Identity keys of an existing Zotero item (for deduplication)."""
    ids = {}
    extra = data.get("extra", "") or ""
    doi = data.get("DOI") or ""
    if not doi:
        m = re.search(r"^DOI:\s*(\S+)", extra, re.M | re.I)
        doi = m.group(1) if m else ""
    if doi:
        ids["doi"] = normalize_doi(doi)
        am = re.match(r"10\.48550/arxiv\.(.+)", ids["doi"])
        if am:
            ids["arxiv"] = am.group(1)
    blob = " ".join(str(data.get(k, "")) for k in ("archiveID", "url", "extra"))
    m = ARXIV_RE.search(blob)
    if m:
        ids["arxiv"] = m.group(1).lower()
    m = re.search(r"^Citation Key:\s*(\S+)", extra, re.M | re.I)
    if m:
        ids["citekey"] = m.group(1)
    if data.get("citationKey"):
        ids["citekey"] = data["citationKey"]
    if data.get("title"):
        ids["title"] = norm_title(data["title"])
    return ids
