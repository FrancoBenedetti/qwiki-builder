"""
Unit tests for Qwiki Project Manifest loading, saving, and auto-discovery.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qwikibuilder.manifest import (
    CategoryItem,
    DocumentItem,
    QwikiProjectManifest,
    extract_title_from_html,
    extract_title_from_markdown,
    slugify,
)


class TestManifest(unittest.TestCase):

    def test_slugify(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")
        self.assertEqual(slugify("SOP-001: General Operations"), "sop-001-general-operations")
        self.assertEqual(slugify("  Lots   of    spaces   "), "lots-of-spaces")

    def test_extract_titles(self):
        md = "# My Document Title\n\nSome body text..."
        self.assertEqual(extract_title_from_markdown(md, "Default"), "My Document Title")

        html = "<html><head><title>HTML Doc Title</title></head><body><h1>Main Heading</h1></body></html>"
        self.assertEqual(extract_title_from_html(html, "Default"), "Main Heading")

    def test_save_and_load_manifest(self):
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            manifest = QwikiProjectManifest(
                name="Test Suite",
                slug="test-suite",
                version="1.0.0",
                categories=[CategoryItem(id="cat1", title="Category One")],
                documents=[
                    DocumentItem(
                        file="doc1.md",
                        category="cat1",
                        slug="doc-one",
                        title="Document One",
                    )
                ],
                project_root=tmp_path,
            )
            saved_path = manifest.save(tmp_path / "qwiki-project.json")
            self.assertTrue(saved_path.is_file())

            loaded = QwikiProjectManifest.load(saved_path)
            self.assertEqual(loaded.name, "Test Suite")
            self.assertEqual(len(loaded.categories), 1)
            self.assertEqual(len(loaded.documents), 1)
            self.assertEqual(loaded.documents[0].slug, "doc-one")

    def test_auto_discovery(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docs_dir = root / "docs"
            cat_dir = docs_dir / "01-operations"
            cat_dir.mkdir(parents=True)

            (cat_dir / "step1.md").write_text("# Step One Procedure\n\nContent here", encoding="utf-8")
            (cat_dir / "step2.md").write_text("# Step Two Procedure\n\nContent here", encoding="utf-8")

            manifest = QwikiProjectManifest(project_root=root)
            manifest.auto_discover()

            self.assertEqual(len(manifest.documents), 2)
            self.assertTrue(any(c.id == "01-operations" for c in manifest.categories))
            self.assertTrue(any(d.slug == "step1" and d.title == "Step One Procedure" for d in manifest.documents))


if __name__ == "__main__":
    unittest.main()
