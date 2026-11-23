"""Configuration: .zotero.toml (committed, no secrets) + environment / .env (secrets)."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = ".zotero.toml"

# Only these variables are read from a project's .env. Anything else (in particular
# ZOTERO_API_URL, which decides where the key is sent) must come from the real environment,
# so a .env committed to a cloned repo cannot redirect your key.
DOTENV_KEYS = {
    "ZOTERO_API_KEY", "ZOTERO_LIBRARY_ID", "ZOTERO_LIBRARY_TYPE", "ZOTERO_COLLECTION",
    "ZOTERO_LOCAL", "CROSSREF_MAILTO",
}


class ConfigError(Exception):
    pass


def find_project_root(start: Path | None = None) -> Path:
    """Directory containing .zotero.toml, else the git root, else cwd."""
    start = (start or Path.cwd()).resolve()
    for d in (start, *start.parents):
        if (d / CONFIG_NAME).exists():
            return d
    for d in (start, *start.parents):
        if (d / ".git").exists():
            return d
    return start


def load_dotenv(path: Path) -> None:
    """Minimal .env loader. Never overrides variables already set in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # inline comment
        if key in DOTENV_KEYS:
            os.environ.setdefault(key, value)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    root: Path
    library_type: str = "group"
    library_id: str = ""
    api_key: str = field(default="", repr=False)  # never printed
    local: bool = False
    collection: str = ""
    tags: list[str] = field(default_factory=list)
    # pull
    bib_output: str = "references.bib"
    bib_format: str = "biblatex"
    # push
    ids_files: list[str] = field(default_factory=list)
    bib_files: list[str] = field(default_factory=list)
    pdf_dirs: list[str] = field(default_factory=list)
    upload_pdfs: bool = False

    @property
    def prefix(self) -> str:
        if self.local and self.library_type == "user":
            return "/users/0"
        return f"/{self.library_type}s/{self.library_id}"

    def require_library(self) -> None:
        if self.library_type not in {"user", "group"}:
            raise ConfigError("library_type must be 'user' or 'group'")
        if not self.library_id and not (self.local and self.library_type == "user"):
            raise ConfigError(
                "No library configured. Set library_id in .zotero.toml or ZOTERO_LIBRARY_ID."
            )
        if self.library_id and not self.library_id.isdigit():
            raise ConfigError(f"library_id must be numeric, got {self.library_id!r}")
        if self.collection and not re.fullmatch(r"[A-Za-z0-9]{8}", self.collection):
            raise ConfigError(f"collection must be an 8-character key (see `zt collections`), "
                              f"got {self.collection!r}")

    def require_key(self) -> None:
        if not self.local and not self.api_key:
            raise ConfigError(
                "ZOTERO_API_KEY is not set. Put it in the project's .env (git-ignored) "
                "or export it in your shell. See docs/01-api-key.md."
            )


def load_config(root: Path | None = None) -> Config:
    root = root or find_project_root()
    load_dotenv(root / ".env")

    data: dict = {}
    cfg_path = root / CONFIG_NAME
    if cfg_path.is_file():
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
        for forbidden in ("api_key", "key", "token"):
            if forbidden in data:
                raise ConfigError(
                    f"'{forbidden}' found in {CONFIG_NAME}. Secrets belong in .env, not in a committed file."
                )

    pull = data.get("pull", {})
    push = data.get("push", {})
    cfg = Config(
        root=root,
        library_type=str(data.get("library_type", "group")),
        library_id=str(data.get("library_id", "")),
        collection=str(data.get("collection", "")),
        tags=list(data.get("tags", [])),
        bib_output=str(pull.get("output", "references.bib")),
        bib_format=str(pull.get("format", "biblatex")),
        ids_files=list(push.get("ids_files", [])),
        bib_files=list(push.get("bib_files", [])),
        pdf_dirs=list(push.get("pdf_dirs", [])),
        upload_pdfs=bool(push.get("upload_pdfs", False)),
    )

    # Environment overrides
    env = os.environ
    cfg.api_key = env.get("ZOTERO_API_KEY", "").strip()
    if env.get("ZOTERO_LIBRARY_ID"):
        cfg.library_id = env["ZOTERO_LIBRARY_ID"].strip()
    if env.get("ZOTERO_LIBRARY_TYPE"):
        cfg.library_type = env["ZOTERO_LIBRARY_TYPE"].strip().lower()
    if env.get("ZOTERO_COLLECTION"):
        cfg.collection = env["ZOTERO_COLLECTION"].strip()
    cfg.local = _truthy(env.get("ZOTERO_LOCAL"))
    return cfg
