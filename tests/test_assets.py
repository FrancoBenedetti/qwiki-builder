"""
Unit tests for AssetManager in qwikibuilder.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from qwikibuilder.assets import AssetManager
from qwikibuilder.client import QwikiClient


class TestAssetManager(unittest.TestCase):

    def setUp(self):
        self.mock_client = MagicMock(spec=QwikiClient)

    def test_upload_file_image_and_video(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            assets_dir = root / "docs" / "assets"
            assets_dir.mkdir(parents=True)

            img_file = assets_dir / "diagram.png"
            img_file.write_bytes(b"fake-png-data")

            vid_file = assets_dir / "walkthrough.mp4"
            vid_file.write_bytes(b"fake-mp4-data")

            self.mock_client.upload_image.side_effect = [
                {"success": True, "url": "uploads/images/1792-diagram.png"},
                {"success": True, "url": "uploads/videos/1792-walkthrough.mp4"},
            ]

            mgr = AssetManager(self.mock_client, assets_dir)

            # Upload image
            img_url = mgr.upload_file(img_file)
            self.assertEqual(img_url, "uploads/images/1792-diagram.png")

            # Upload video
            vid_url = mgr.upload_file(vid_file)
            self.assertEqual(vid_url, "uploads/videos/1792-walkthrough.mp4")

            # Check cache usage: subsequent call doesn't re-invoke client
            self.mock_client.upload_image.reset_mock()
            cached_url = mgr.upload_file(img_file)
            self.assertEqual(cached_url, "uploads/images/1792-diagram.png")
            self.mock_client.upload_image.assert_not_called()

    def test_process_content_assets_rewriting(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            docs_dir = root / "docs"
            assets_dir = docs_dir / "assets"
            images_dir = assets_dir / "images"
            videos_dir = assets_dir / "videos"
            images_dir.mkdir(parents=True)
            videos_dir.mkdir(parents=True)

            # Create test files
            (images_dir / "screenshot.png").write_bytes(b"fake-image")
            (videos_dir / "demo.mp4").write_bytes(b"fake-video")

            self.mock_client.upload_image.side_effect = [
                {"success": True, "url": "uploads/images/100-screenshot.png"},
                {"success": True, "url": "uploads/videos/200-demo.mp4"},
                {"success": True, "url": "uploads/images/300-html-img.png"},
            ]
            (images_dir / "html-img.png").write_bytes(b"fake-html-image")

            mgr = AssetManager(self.mock_client, assets_dir)

            content = (
                "# Document Title\n\n"
                "Here is a screenshot:\n"
                "![Dashboard Screenshot](assets/images/screenshot.png)\n\n"
                "Here is an embedded video walkthrough:\n"
                "[Watch Feature Demo](assets/videos/demo.mp4)\n\n"
                '<img src="assets/images/html-img.png" alt="HTML Tag" />\n'
            )

            rewritten, referenced = mgr.process_content_assets(content, docs_dir, auto_upload=True)

            self.assertIn("![Dashboard Screenshot](uploads/images/100-screenshot.png)", rewritten)
            self.assertIn("[Watch Feature Demo](uploads/videos/200-demo.mp4)", rewritten)
            self.assertIn('<img src="uploads/images/300-html-img.png" alt="HTML Tag" />', rewritten)
            self.assertEqual(len(referenced), 3)


if __name__ == "__main__":
    unittest.main()
