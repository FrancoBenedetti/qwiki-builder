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


if __name__ == "__main__":
    unittest.main()
