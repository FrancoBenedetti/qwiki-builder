"""
Unit tests for theme CSS manifest, validation, client, publisher, and CLI support.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from qwikibuilder.cli import main as cli_main
from qwikibuilder.client import QwikiClient
from qwikibuilder.manifest import CategoryItem, DocumentItem, QwikiProjectManifest
from qwikibuilder.publisher import QwikiPublisher
from qwikibuilder.validator import ProjectValidator


class TestThemes(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs" / "guides").mkdir(parents=True)
        (self.root / "docs" / "assets" / "themes").mkdir(parents=True)
        (self.root / "docs" / "guides" / "intro.md").write_text("# Intro\n\nHello.\n", encoding="utf-8")
        self.custom_css = self.root / "docs" / "assets" / "themes" / "theme-custom-md.css"
        self.custom_css.write_text(".content-body h2 { color: teal; }\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_theme_roundtrip_and_resolution(self):
        manifest = QwikiProjectManifest(
            name="Themed Docs",
            slug="themed-docs",
            theme="docs/assets/themes/theme-custom-md.css",
            categories=[CategoryItem(id="guides", title="Guides", theme="theme-article-classic.css")],
            documents=[DocumentItem(file="guides/intro.md", category="guides", slug="intro", title="Intro", theme="theme-article-modern.css")],
            project_root=self.root,
        )
        saved_path = manifest.save()
        loaded = QwikiProjectManifest.load(saved_path)

        self.assertEqual(loaded.theme, "docs/assets/themes/theme-custom-md.css")
        self.assertEqual(loaded.categories[0].theme, "theme-article-classic.css")
        self.assertEqual(loaded.documents[0].theme, "theme-article-modern.css")

        name, local_path = loaded.resolve_theme_ref(loaded.theme)
        self.assertEqual(name, "theme-custom-md.css")
        self.assertEqual(local_path, self.custom_css.resolve())

    def test_validator_rejects_bad_theme_name_and_missing_file(self):
        manifest = QwikiProjectManifest(
            name="Bad Theme",
            slug="bad-theme",
            theme="docs/assets/themes/missing-theme.css",
            categories=[CategoryItem(id="guides", title="Guides", theme="bad-name.css")],
            documents=[DocumentItem(file="guides/intro.md", category="guides", slug="intro", title="Intro")],
            project_root=self.root,
        )
        report = ProjectValidator(manifest).validate()
        self.assertFalse(report.is_valid)
        self.assertTrue(any("not found on disk" in i.message for i in report.errors))
        self.assertTrue(any("theme-<name>.css" in i.message for i in report.errors))

    @patch("urllib.request.urlopen")
    def test_client_theme_methods(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "siteTheme": "theme-default.css",
            "themes": ["theme-default.css", "theme-custom-md.css"],
            "theme": "theme-custom-md.css",
            "url": "uploads/themes/theme-custom-md.css",
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = QwikiClient("https://wiki.example.com", "key")
        listed = client.list_themes()
        self.assertEqual(listed["siteTheme"], "theme-default.css")
        saved = client.save_theme("theme-custom-md.css", ".content-body { color: #111; }")
        self.assertEqual(saved["theme"], "theme-custom-md.css")
        applied = client.set_site_theme("theme-custom-md.css")
        self.assertEqual(applied["theme"], "theme-custom-md.css")

    def test_publisher_syncs_local_themes_and_applies_scopes(self):
        manifest = QwikiProjectManifest(
            name="Themed Docs",
            slug="themed-docs",
            theme="docs/assets/themes/theme-custom-md.css",
            categories=[CategoryItem(id="guides", title="Guides", theme="theme-article-classic.css")],
            documents=[DocumentItem(file="guides/intro.md", category="guides", slug="intro", title="Intro", theme="theme-article-modern.css")],
            project_root=self.root,
        )
        mock_client = MagicMock(spec=QwikiClient)
        mock_client.base_url = "https://wiki.example.com"
        mock_client.list_categories.return_value = []
        mock_client.create_category.return_value = {"success": True}
        mock_client.publish_document.return_value = {
            "success": True,
            "updated": False,
            "slug": "intro",
            "bookId": "guides",
            "docId": "d1",
            "shareKey": "abc",
            "status": "published",
            "sha256": "f" * 64,
            "url": "https://wiki.example.com/guides/intro",
        }

        publisher = QwikiPublisher(manifest, mock_client)
        res = publisher.publish_all(dry_run=False, upload_assets_first=False)
        self.assertTrue(res["success"])
        mock_client.save_theme.assert_called_with("theme-custom-md.css", ".content-body h2 { color: teal; }\n")
        mock_client.set_site_theme.assert_called_with("theme-custom-md.css")
        mock_client.create_category.assert_called_with(
            category_id="guides",
            title="Guides",
            description="",
            parent=None,
            theme="theme-article-classic.css",
        )
        self.assertEqual(mock_client.publish_document.call_args.kwargs["theme"], "theme-article-modern.css")

    @patch("qwikibuilder.cli.QwikiClient.save_theme")
    @patch("qwikibuilder.cli.QwikiClient.set_site_theme")
    def test_cli_theme_apply_site(self, mock_set_site, mock_save_theme):
        mock_save_theme.return_value = {"success": True, "theme": "theme-custom-md.css"}
        mock_set_site.return_value = {"success": True, "theme": "theme-custom-md.css"}

        rc = cli_main([
            "theme", "apply", str(self.custom_css),
            "--site",
            "--url", "https://wiki.example.com",
            "--key", "dummy_key",
        ])
        self.assertEqual(rc, 0)
        mock_save_theme.assert_called_once()
        mock_set_site.assert_called_once_with("theme-custom-md.css")
