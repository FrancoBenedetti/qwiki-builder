import tempfile
import unittest
from pathlib import Path

from qwikibuilder.links import LinkManager
from qwikibuilder.manifest import CategoryItem, DocumentItem, QwikiProjectManifest


class TestLinkManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.docs_dir = self.root / "docs"
        self.docs_dir.mkdir()

        # Create two subfolders
        (self.docs_dir / "cat1").mkdir()
        (self.docs_dir / "cat2").mkdir()

        self.file1 = self.docs_dir / "cat1" / "doc1.md"
        self.file1.write_text("# Doc 1\nLink to [Doc 2](doc-2) and [Doc 2 by file](../cat2/doc2.md).", encoding="utf-8")

        self.file2 = self.docs_dir / "cat2" / "doc2.md"
        self.file2.write_text("# Doc 2\nLink back to [Doc 1](cat1/doc-1).", encoding="utf-8")

        self.manifest = QwikiProjectManifest(
            name="Link Test",
            slug="link-test",
            categories=[
                CategoryItem(id="cat1", title="Category 1"),
                CategoryItem(id="cat2", title="Category 2"),
            ],
            documents=[
                DocumentItem(file="cat1/doc1.md", category="cat1", slug="doc-1", title="Doc 1"),
                DocumentItem(file="cat2/doc2.md", category="cat2", slug="doc-2", title="Doc 2"),
            ],
            project_root=self.root,
        )
        self.link_manager = LinkManager(self.manifest)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_slug(self):
        resolved = self.link_manager.resolve_target("doc-2", doc_dir=self.file1.parent)
        self.assertEqual(resolved, "cat2/doc-2")

    def test_resolve_relative_path(self):
        resolved = self.link_manager.resolve_target("../cat2/doc2.md", doc_dir=self.file1.parent)
        self.assertEqual(resolved, "cat2/doc-2")

    def test_resolve_with_anchor(self):
        resolved = self.link_manager.resolve_target("doc-2#section-step", doc_dir=self.file1.parent)
        self.assertEqual(resolved, "cat2/doc-2#section-step")

    def test_process_content_links(self):
        sample = "See [Doc 2](doc-2) or [By file](cat2/doc2.md) or [Ext](https://example.com) or [Img](assets/pic.png)."
        processed, rewrites = self.link_manager.process_content_links(sample, doc_dir=self.file1.parent)
        self.assertIn("[Doc 2](cat2/doc-2)", processed)
        self.assertIn("[By file](cat2/doc-2)", processed)
        self.assertIn("[Ext](https://example.com)", processed)
        # Image is not a markdown doc link if written as ![Img](...)
        img_sample = "![Diagram](assets/diagram.png) and [Doc](doc-2)"
        img_processed, _ = self.link_manager.process_content_links(img_sample, doc_dir=self.file1.parent)
        self.assertIn("![Diagram](assets/diagram.png)", img_processed)
        self.assertIn("[Doc](cat2/doc-2)", img_processed)
