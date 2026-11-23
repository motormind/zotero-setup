"""Offline tests (no network). Run: python3 -m unittest discover -s tests"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from zotero_setup.config import ConfigError, load_config  # noqa: E402
from zotero_setup.sources import (  # noqa: E402
    fit_to_template, from_bibtex_entry, item_identity, parse_bibtex, parse_identifier,
)

BIB = r"""
@comment{ignored}
@article{lecun2015,
  title = {Deep {L}earning}, author = {LeCun, Yann and Geoffrey Hinton},
  journal = "Nature", year = 2015, pages = {436--444}, doi = {https://doi.org/10.1038/NATURE14539}
}
@misc{vaswani2017, title={Attention Is All You Need}, eprint={1706.03762}, archivePrefix={arXiv},
  author={Vaswani, Ashish and {Google Brain}}}
"""


class TestIdentifiers(unittest.TestCase):
    def test_parse(self):
        cases = {
            "10.1038/nature14539": ("doi", "10.1038/nature14539"),
            "https://doi.org/10.1038/Nature14539.": ("doi", "10.1038/nature14539"),
            "doi:10.1145/3065386": ("doi", "10.1145/3065386"),
            "arXiv:2005.14165v4": ("arxiv", "2005.14165"),
            "https://arxiv.org/pdf/1810.04805": ("arxiv", "1810.04805"),
            "1706.03762": ("arxiv", "1706.03762"),
            "10.48550/arXiv.1706.03762": ("arxiv", "1706.03762"),
        }
        for raw, expected in cases.items():
            self.assertEqual(parse_identifier(raw), expected, raw)
        self.assertEqual(parse_identifier("hello")[0], "")


class TestBibtex(unittest.TestCase):
    def setUp(self):
        self.entries = parse_bibtex(BIB)

    def test_entries(self):
        self.assertEqual([e["_key"] for e in self.entries], ["lecun2015", "vaswani2017"])

    def test_article(self):
        it = from_bibtex_entry(self.entries[0])
        self.assertEqual(it["itemType"], "journalArticle")
        self.assertEqual(it["title"], "Deep Learning")
        self.assertEqual(it["publicationTitle"], "Nature")
        self.assertEqual(it["pages"], "436-444")
        self.assertEqual(it["DOI"], "10.1038/nature14539")
        self.assertEqual(it["creators"][1], {"creatorType": "author", "lastName": "Hinton", "firstName": "Geoffrey"})
        self.assertIn("Citation Key: lecun2015", it["_extra"])

    def test_arxiv_misc(self):
        it = from_bibtex_entry(self.entries[1])
        self.assertEqual(it["itemType"], "preprint")
        self.assertEqual(it["archiveID"], "arXiv:1706.03762")
        self.assertEqual(it["creators"][1], {"creatorType": "author", "name": "Google Brain"})

    def test_fit_and_identity(self):
        it = from_bibtex_entry(self.entries[0])
        tpl = {"itemType": "journalArticle", "title": "", "creators": [], "DOI": "", "pages": "",
               "publicationTitle": "", "extra": "", "tags": [], "collections": [], "relations": {}}
        out = fit_to_template(it, tpl, ["src:x"], "COLL0001")
        self.assertNotIn("volume", out)                       # unknown fields dropped
        self.assertEqual(out["extra"], "Citation Key: lecun2015")  # DOI not duplicated
        self.assertEqual(out["collections"], ["COLL0001"])
        ids = item_identity(out)
        self.assertEqual(ids["doi"], "10.1038/nature14539")
        self.assertEqual(ids["citekey"], "lecun2015")


class TestConfig(unittest.TestCase):
    def test_rejects_secret_in_toml(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".zotero.toml").write_text('library_id = "1"\napi_key = "x"\n')
            with self.assertRaises(ConfigError):
                load_config(Path(d))

    def test_env_file_and_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".zotero.toml").write_text('library_id = "1"\ncollection = "C"\n')
            Path(d, ".env").write_text('ZOTERO_API_KEY="k123"\nexport ZOTERO_COLLECTION=D\n')
            for k in ("ZOTERO_API_KEY", "ZOTERO_COLLECTION", "ZOTERO_LIBRARY_ID", "ZOTERO_LOCAL"):
                os.environ.pop(k, None)
            try:
                cfg = load_config(Path(d))
                self.assertEqual(cfg.api_key, "k123")
                self.assertEqual(cfg.collection, "D")
                self.assertEqual(cfg.prefix, "/groups/1")
                self.assertNotIn("k123", repr(cfg))
            finally:
                os.environ.pop("ZOTERO_API_KEY", None)
                os.environ.pop("ZOTERO_COLLECTION", None)


if __name__ == "__main__":
    unittest.main()


class TestHardening(unittest.TestCase):
    def test_paren_in_abstract_does_not_end_entry(self):
        e = parse_bibtex("@article{k, abstract={a) one b) two}, title={T}, year={2020}, month=jun}")[0]
        self.assertEqual(e["title"], "T")
        self.assertEqual(from_bibtex_entry(e)["date"], "2020-06")

    def test_dotenv_cannot_redirect_api(self):
        from zotero_setup.config import load_dotenv
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text("ZOTERO_API_URL=https://evil.example\nZOTERO_LOCAL=true # note\n")
            for k in ("ZOTERO_API_URL", "ZOTERO_LOCAL"):
                os.environ.pop(k, None)
            try:
                load_dotenv(Path(d, ".env"))
                self.assertNotIn("ZOTERO_API_URL", os.environ)
                self.assertEqual(os.environ["ZOTERO_LOCAL"], "true")
            finally:
                os.environ.pop("ZOTERO_LOCAL", None)

    def test_invalid_ids_rejected(self):
        from zotero_setup.config import Config
        with self.assertRaises(ConfigError):
            Config(root=Path("."), library_id="1/../../keys").require_library()
        with self.assertRaises(ConfigError):
            Config(root=Path("."), library_id="1", collection="../x").require_library()

    def test_key_only_goes_to_api_origin(self):
        from zotero_setup.api import Zotero, ZoteroError, _origin
        self.assertNotEqual(_origin("https://api.zotero.org.evil.example/x"), _origin("https://api.zotero.org"))
        with self.assertRaises(ZoteroError):
            Zotero("/groups/1", "k" * 24, base="http://example.org")

    def test_files_outside_project_are_ignored(self):
        from zotero_setup.cli import _resolve_globs
        with tempfile.TemporaryDirectory() as d, tempfile.NamedTemporaryFile(suffix=".pdf") as outside:
            root = Path(d)
            (root / "papers").mkdir()
            (root / "papers" / "ok.pdf").write_bytes(b"%PDF")
            (root / "papers" / "link.pdf").symlink_to(outside.name)
            self.assertEqual([p.name for p in _resolve_globs(root, ["papers/*.pdf"])], ["ok.pdf"])
            with self.assertRaises(ConfigError):
                _resolve_globs(root, ["../*.pdf"])

    def test_unique_citekeys(self):
        from zotero_setup.cli import _unique_citekeys
        text, renamed = _unique_citekeys("@article{a,\n}\n@book{a,\n}\n@misc{b,\n}\n")
        self.assertIn("@book{a-2,", text)
        self.assertEqual(renamed, ["a -> a-2"])
