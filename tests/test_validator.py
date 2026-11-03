"""
Unit tests for ProjectValidator.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qwikibuilder.manifest import CategoryItem, DocumentItem, QwikiProjectManifest
from qwikibuilder.validator import ProjectValidator


class TestValidator(unittest.TestCase):

    def test_valid_project(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "intro.md").write_text("# Intro\n\nWelcome to docs.", encoding="utf-8")

            manifest = QwikiProjectManifest(
                categories=[CategoryItem(id="general", title="General")],
                documents=[
                    DocumentItem(
                        file="intro.md",
                        category="general",
                        slug="intro",
                        title="Intro",
                    )
                ],
                project_root=root,
            )

            validator = ProjectValidator(manifest)
            report = validator.validate()
            self.assertTrue(report.is_valid)
            self.assertEqual(len(report.errors), 0)

    def test_missing_file_error(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "docs").mkdir()

            manifest = QwikiProjectManifest(
                categories=[CategoryItem(id="general", title="General")],
                documents=[
                    DocumentItem(
                        file="non_existent.md",
                        category="general",
                        slug="non-existent",
                        title="Ghost File",
                    )
                ],
                project_root=root,
            )

            validator = ProjectValidator(manifest)
            report = validator.validate()
            self.assertFalse(report.is_valid)
            self.assertTrue(any("does not exist" in e.message for e in report.errors))

    def test_duplicate_slug_error(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docs = root / "docs"
            docs.mkdir()
            (docs / "doc1.md").write_text("# Doc 1", encoding="utf-8")
            (docs / "doc2.md").write_text("# Doc 2", encoding="utf-8")

            manifest = QwikiProjectManifest(
                categories=[CategoryItem(id="general", title="General")],
                documents=[
                    DocumentItem(file="doc1.md", category="general", slug="same-slug", title="Doc 1"),
                    DocumentItem(file="doc2.md", category="general", slug="same-slug", title="Doc 2"),
                ],
                project_root=root,
            )

            validator = ProjectValidator(manifest)
            report = validator.validate()
            self.assertFalse(report.is_valid)
            self.assertTrue(any("Duplicate slug" in e.message for e in report.errors))


if __name__ == "__main__":
    unittest.main()
