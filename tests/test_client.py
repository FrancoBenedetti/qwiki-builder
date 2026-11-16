"""
Unit tests for QwikiClient with mocked HTTP requests.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from qwikibuilder.client import QwikiClient, QwikiClientError


class TestClient(unittest.TestCase):

    def setUp(self):
        self.client = QwikiClient("https://wiki.example.com", "dummy_key")

    @patch("urllib.request.urlopen")
    def test_list_categories_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "categories": [{"id": "user-guide", "title": "User Guide"}]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        cats = self.client.list_categories()
        self.assertEqual(len(cats), 1)
        self.assertEqual(cats[0]["id"], "user-guide")

    @patch("urllib.request.urlopen")
    def test_publish_document_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "updated": True,
            "slug": "intro",
            "url": "https://wiki.example.com/user-guide/intro",
            "shareKey": "abc12345"
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = self.client.publish_document(
            book_id="user-guide",
            title="Introduction",
            content="# Intro\n\nContent",
            slug="intro",
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["slug"], "intro")

    @patch("urllib.request.urlopen")
    def test_api_error_raises_exception(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "success": False,
            "error": "Category not found"
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with self.assertRaises(QwikiClientError):
            self.client.list_categories()

    @patch("urllib.request.urlopen")
    def test_get_document_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "document": {
                "slug": "intro",
                "bookId": "user-guide",
                "title": "Introduction",
                "type": "markdown",
                "sha256": "a" * 64,
                "content": "# Introduction\n\nLive edited.",
                "commentsCount": 1,
                "comments": [{"author": "alice", "content": "Add screenshot"}],
                "talkTopicsCount": 1,
                "talkRaw": "## Clarification\nUpdate step 2.",
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        doc = self.client.get_document(slug="intro", book_id="user-guide")
        self.assertEqual(doc["slug"], "intro")
        self.assertEqual(doc["sha256"], "a" * 64)
        self.assertEqual(doc["commentsCount"], 1)
        self.assertIn("Clarification", doc["talkRaw"])

    @patch("urllib.request.urlopen")
    def test_publish_document_conflict_parses_error_code(self, mock_urlopen):
        import io
        import urllib.error

        err_payload = json.dumps({
            "success": False,
            "code": "CONFLICT_SHA256_MISMATCH",
            "expectedSha256": "0" * 64,
            "actualSha256": "b" * 64,
            "error": "Document has changed on the remote wiki",
        }).encode("utf-8")
        http_err = urllib.error.HTTPError(
            url="https://wiki.example.com/api/publish.php",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=io.BytesIO(err_payload),
        )
        mock_urlopen.side_effect = http_err

        with self.assertRaises(QwikiClientError) as ctx:
            self.client.publish_document(
                book_id="user-guide",
                title="Introduction",
                content="# Intro",
                slug="intro",
                expected_sha256="0" * 64,
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.error_code, "CONFLICT_SHA256_MISMATCH")
        self.assertEqual(ctx.exception.response_data.get("actualSha256"), "b" * 64)


if __name__ == "__main__":
    unittest.main()
