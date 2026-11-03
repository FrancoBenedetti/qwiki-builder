"""
Unit tests for Qwiki Builder configuration and profile resolution.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from qwikibuilder.config import (
    delete_profile,
    get_profile,
    list_profiles,
    resolve_credentials,
    set_profile,
)


class TestConfig(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = TemporaryDirectory()
        self.patcher = patch("qwikibuilder.config.get_global_config_dir", return_value=Path(self.tmp_dir.name))
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    def test_set_and_get_profile(self):
        set_profile("test-profile", "https://wiki.example.com/test", "key_12345", set_default=True)
        prof = get_profile("test-profile")
        self.assertIsNotNone(prof)
        self.assertEqual(prof["url"], "https://wiki.example.com/test")
        self.assertEqual(prof["api_key"], "key_12345")

        def_prof = get_profile(None)
        self.assertEqual(def_prof["url"], "https://wiki.example.com/test")

    def test_list_and_delete_profile(self):
        set_profile("prof1", "https://w1.com", "k1")
        set_profile("prof2", "https://w2.com", "k2")
        profs = list_profiles()
        self.assertIn("prof1", profs)
        self.assertIn("prof2", profs)

        deleted = delete_profile("prof1")
        self.assertTrue(deleted)
        self.assertNotIn("prof1", list_profiles())

    def test_resolve_credentials_precedence(self):
        # Explicit CLI overrides all
        url, key = resolve_credentials(
            explicit_url="https://cli.example.com",
            explicit_key="cli_key",
            project_url="https://project.example.com",
            project_key="proj_key",
        )
        self.assertEqual(url, "https://cli.example.com")
        self.assertEqual(key, "cli_key")

        # Project fallback
        url2, key2 = resolve_credentials(
            project_url="https://project.example.com",
            project_key="proj_key",
        )
        self.assertEqual(url2, "https://project.example.com")
        self.assertEqual(key2, "proj_key")

    def test_resolve_credentials_missing_raises_error(self):
        with self.assertRaises(ValueError):
            resolve_credentials()


if __name__ == "__main__":
    unittest.main()
