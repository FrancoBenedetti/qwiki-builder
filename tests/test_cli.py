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

    def test_cli_forms_and_status_commands(self):
        from unittest.mock import MagicMock, patch

        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            form_file = root / "feedback.form.json"
            form_file.write_text(
                '{"title": "Feedback", "fields": [{"id": "name", "label": "Name", "type": "text"}]}',
                encoding="utf-8",
            )

            mock_client = MagicMock()
            mock_client.base_url = "https://wiki.example.com"
            mock_client.list_forms.return_value = [
                {
                    "bookId": "general",
                    "slug": "feedback",
                    "title": "Feedback",
                    "fieldsCount": 1,
                    "submissionsCount": 2,
                    "latestSubmissionAt": "2026-11-21 10:00:00",
                    "url": "https://wiki.example.com/general/feedback",
                }
            ]
            mock_client.publish_document.return_value = {
                "success": True,
                "updated": False,
                "bookId": "general",
                "slug": "feedback",
                "url": "https://wiki.example.com/general/feedback",
            }
            mock_client.get_form_submissions.return_value = {
                "success": True,
                "returned": 1,
                "total": 1,
                "schema": {"fields": [{"id": "name", "label": "Name", "type": "text"}]},
                "submissions": [
                    {
                        "id": "sub_123",
                        "created_at": "2026-11-21 10:00:00",
                        "submitted_by": "guest",
                        "data": {"name": "Alice"},
                    }
                ],
                "csv": "Submission ID,Name\nsub_123,Alice\n",
            }

            with patch("qwikibuilder.cli._get_client_optional_manifest", return_value=(None, mock_client)):
                self.assertEqual(main(["forms", "list"]), 0)
                self.assertEqual(main(["forms", "push", str(form_file), "--category", "general"]), 0)
                csv_out = root / "out.csv"
                self.assertEqual(
                    main(["forms", "responses", "feedback", "--format", "csv", "-o", str(csv_out)]),
                    0,
                )
                self.assertTrue(csv_out.is_file())
                self.assertIn("Alice", csv_out.read_text(encoding="utf-8"))
                self.assertEqual(main(["forms", "watch", "feedback", "--max-polls", "1", "--interval", "2"]), 0)


if __name__ == "__main__":
    unittest.main()
