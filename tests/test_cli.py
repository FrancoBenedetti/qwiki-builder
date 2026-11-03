"""
Unit tests for CLI commands.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from qwikibuilder.cli import main


class TestCli(unittest.TestCase):

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_cli_init_and_validate_all_templates(self):
        templates = ["user-guide", "equipment-manual", "quality-manual", "safety-handbook", "sop", "blank"]
        with TemporaryDirectory() as tmp_dir:
            for t in templates:
                proj_dir = Path(tmp_dir) / t
                code = main(["init", str(proj_dir), "--template", t, "--name", f"Test {t}"])
                self.assertEqual(code, 0, f"Failed init for template {t}")
                val_code = main(["validate", str(proj_dir)])
                self.assertEqual(val_code, 0, f"Failed validation for template {t}")


if __name__ == "__main__":
    unittest.main()
