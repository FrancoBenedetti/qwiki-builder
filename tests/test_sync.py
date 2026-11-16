"""
Unit tests for SyncManager, pull/diff reconciliation, feedback sidecars, and optimistic concurrency.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from qwikibuilder.client import QwikiClientError
from qwikibuilder.manifest import CategoryItem, DocumentItem, QwikiProjectManifest
from qwikibuilder.publisher import QwikiPublisher
from qwikibuilder.sync import SyncManager, sha256_text


class TestSync(unittest.TestCase):

    def _make_project(self, root: Path, content: str = "# Intro\n\nLine 1\n"):
        docs = root / "docs" / "general"
        docs.mkdir(parents=True, exist_ok=True)
        doc_path = docs / "intro.md"
        doc_path.write_text(content, encoding="utf-8")
        doc = DocumentItem(
            file="general/intro.md",
            category="general",
            slug="intro",
            title="Intro",
            status="published",
        )
        manifest = QwikiProjectManifest(
            name="Test Docs",
            slug="test-docs",
            categories=[CategoryItem(id="general", title="General")],
            documents=[doc],
            project_root=root,
        )
        manifest.save(root / "qwiki-project.json")
        return manifest, doc, doc_path

    def test_pull_writes_feedback_sidecars_and_updates_unmodified_local(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            v1 = "# Intro\n\nOriginal line.\n"
            manifest, doc, doc_path = self._make_project(root, content=v1)

            client = MagicMock()
            sync = SyncManager(manifest, client)
            sync.record_synced_baseline("intro", "general", "markdown", sha256_text(v1), v1)

            v2_remote = "# Intro\n\nUpdated by live user.\n"
            client.get_document.return_value = {
                "docId": "doc_1234",
                "bookId": "general",
                "slug": "intro",
                "title": "Intro Live",
                "type": "markdown",
                "status": "review",
                "shareKey": "abc123def4567890",
                "sha256": sha256_text(v2_remote),
                "dateModified": "2026-11-16T08:00:00+02:00",
                "lock": {"locked": False},
                "content": v2_remote,
                "commentsEnabled": True,
                "commentsCount": 1,
                "comments": [{"author": "rep1", "role": "viewer", "createdAt": "2026-11-16", "content": "Add nozzle table"}],
                "talkEnabled": True,
                "talkTopicsCount": 1,
                "talkTopics": [{"title": "Review Note", "rawMarkdown": "Please double check rate."}],
                "talkRaw": "## Review Note\nPlease double check rate.\n",
            }

            res = sync.pull_document("intro", doc=doc, sync_meta=True)
            self.assertEqual(res["outcome"], "updated")
            self.assertEqual(doc_path.read_text(encoding="utf-8"), v2_remote)
            self.assertTrue(res["feedback_md"].is_file())
            fb_text = res["feedback_md"].read_text(encoding="utf-8")
            self.assertIn("Add nozzle table", fb_text)
            self.assertIn("Please double check rate.", fb_text)
            self.assertNotIn("Add nozzle table", doc_path.read_text(encoding="utf-8"))
            self.assertEqual(sync.get_expected_sha256("intro"), sha256_text(v2_remote))
            # Metadata synced cleanly
            reloaded = QwikiProjectManifest.load(root / "qwiki-project.json")
            self.assertEqual(reloaded.documents[0].title, "Intro Live")
            self.assertEqual(reloaded.documents[0].status, "review")
            self.assertEqual(reloaded.documents[0].share_key, "abc123def4567890")

    def test_pull_conflict_preserves_local_edits_and_writes_remote_copy(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            local_edit = "# Intro\n\nLocal overlapping edit.\n"
            manifest, doc, doc_path = self._make_project(root, content=local_edit)

            remote_edit = "# Intro\n\nRemote overlapping edit.\n"
            client = MagicMock()
            client.get_document.return_value = {
                "bookId": "general",
                "slug": "intro",
                "title": "Intro",
                "type": "markdown",
                "status": "published",
                "sha256": sha256_text(remote_edit),
                "lock": {"locked": True, "user": "gerhard", "expiresIn": 45},
                "content": remote_edit,
                "commentsCount": 0,
                "comments": [],
                "talkTopicsCount": 0,
                "talkTopics": [],
                "talkRaw": "",
            }

            sync = SyncManager(manifest, client)
            res = sync.pull_document("intro", doc=doc)
            self.assertEqual(res["outcome"], "conflict")
            self.assertEqual(doc_path.read_text(encoding="utf-8"), local_edit)
            self.assertIsNotNone(res["conflict_path"])
            self.assertEqual(res["conflict_path"].read_text(encoding="utf-8"), remote_edit)

    def test_diff_document_reports_unified_diff_and_metadata(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, doc, _ = self._make_project(root, content="# Intro\n\nLocal text.\n")
            client = MagicMock()
            client.get_document.return_value = {
                "bookId": "general",
                "slug": "intro",
                "title": "Intro Renamed",
                "type": "markdown",
                "status": "published",
                "description": "",
                "shareKey": "1234",
                "sha256": "deadbeef" * 8,
                "lock": {"locked": False},
                "content": "# Intro\n\nRemote text.\n",
                "commentsCount": 2,
                "talkTopicsCount": 1,
            }
            sync = SyncManager(manifest, client)
            diff_res = sync.diff_document("intro", doc=doc)
            self.assertTrue(diff_res["content_changed"])
            self.assertIn("-Local text.", diff_res["diff_text"])
            self.assertIn("+Remote text.", diff_res["diff_text"])
            self.assertTrue(any(f == "title" for f, _, _ in diff_res["meta_diffs"]))
            self.assertEqual(diff_res["comments_count"], 2)
            self.assertEqual(diff_res["talk_topics_count"], 1)

    def test_publisher_enforces_tracked_sha256_and_updates_baseline(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = "# Intro\n\nUpdated body.\n"
            manifest, doc, _ = self._make_project(root, content=content)

            client = MagicMock()
            publisher = QwikiPublisher(manifest, client)
            tracked_sha = "1" * 64
            publisher.sync_manager.record_synced_baseline("intro", "general", "markdown", tracked_sha, "# Intro\n\nOld.\n")

            client.publish_document.return_value = {
                "success": True,
                "updated": True,
                "docId": "doc_99",
                "bookId": "general",
                "slug": "intro",
                "sha256": "2" * 64,
                "shareKey": "k1",
                "status": "published",
                "statusUpdatedAt": "2026-11-16T08:10:00+02:00",
                "url": "https://wiki.example.com/general/intro",
            }
            publisher.publish_document_item(doc, update=True)
            _, kwargs = client.publish_document.call_args
            self.assertEqual(kwargs["expected_sha256"], tracked_sha)
            self.assertFalse(kwargs["force"])
            self.assertEqual(publisher.sync_manager.get_expected_sha256("intro"), "2" * 64)

            # Simulate 409 conflict guidance
            client.publish_document.side_effect = QwikiClientError(
                "HTTP 409: Document has changed",
                status_code=409,
                error_code="CONFLICT_SHA256_MISMATCH",
            )
            with self.assertRaises(QwikiClientError) as ctx:
                publisher.publish_document_item(doc, update=True)
            self.assertIn("qwiki-builder pull intro", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
