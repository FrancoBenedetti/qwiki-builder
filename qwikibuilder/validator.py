"""
Validation engine for Qwiki Builder projects.
Verifies file integrity, category references, slugs, assets, and markdown syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from .manifest import QwikiProjectManifest


@dataclass
class ValidationIssue:
    level: str  # 'ERROR' or 'WARNING'
    category: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None


@dataclass
class ValidationReport:
    is_valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.level == "WARNING"]


class ProjectValidator:
    """Validates project structure, manifests, files, and content."""

    def __init__(self, manifest: QwikiProjectManifest):
        self.manifest = manifest
        self.docs_path = manifest.get_docs_path()
        self.assets_path = manifest.get_assets_path()
        self.project_root = manifest.project_root or Path.cwd()

    def validate(self) -> ValidationReport:
        issues: List[ValidationIssue] = []
        stats = {
            "categories": len(self.manifest.categories),
            "documents": len(self.manifest.documents),
            "images": 0,
            "videos": 0,
            "word_count": 0,
        }

        # 1. Validate Categories
        cat_ids: Set[str] = set()
        for cat in self.manifest.categories:
            if not cat.id:
                issues.append(ValidationIssue("ERROR", "Categories", "Category found with empty ID"))
                continue
            if not re.match(r"^[a-zA-Z0-9_\-]+$", cat.id):
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Categories",
                        f"Category ID '{cat.id}' contains invalid characters (use alphanumeric, dash, underscore only)",
                    )
                )
            if cat.id in cat_ids:
                issues.append(ValidationIssue("ERROR", "Categories", f"Duplicate category ID: '{cat.id}'"))
            cat_ids.add(cat.id)
            if not cat.title:
                issues.append(ValidationIssue("WARNING", "Categories", f"Category '{cat.id}' has no title"))

        # 2. Validate Documents
        seen_slugs: Dict[str, str] = {}
        for doc in self.manifest.documents:
            # File existence
            doc_file = (self.docs_path / doc.file).resolve()
            if not doc_file.is_file():
                # Try relative to project root
                cand_root = (self.project_root / doc.file).resolve()
                if cand_root.is_file():
                    doc_file = cand_root
                else:
                    issues.append(
                        ValidationIssue(
                            "ERROR",
                            "Documents",
                            f"Document file does not exist: {doc.file}",
                            file=doc.file,
                        )
                    )
                    continue

            # Category reference
            if doc.category not in cat_ids:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Documents",
                        f"Document '{doc.slug}' references undeclared category '{doc.category}'",
                        file=doc.file,
                    )
                )

            # Slug format and collisions
            if not doc.slug:
                issues.append(ValidationIssue("ERROR", "Documents", f"Missing slug for file {doc.file}", file=doc.file))
            elif not re.match(r"^[a-zA-Z0-9_\-]+$", doc.slug):
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Documents",
                        f"Slug '{doc.slug}' contains invalid characters (alphanumeric, dash, underscore only)",
                        file=doc.file,
                    )
                )
            elif doc.slug in seen_slugs:
                issues.append(
                    ValidationIssue(
                        "ERROR",
                        "Documents",
                        f"Duplicate slug '{doc.slug}' used in '{doc.file}' and '{seen_slugs[doc.slug]}'",
                        file=doc.file,
                    )
                )
            else:
                seen_slugs[doc.slug] = doc.file

            # Content checks
            try:
                content = doc_file.read_text(encoding="utf-8")
                stats["word_count"] += len(content.split())
                if len(content.strip()) == 0:
                    issues.append(ValidationIssue("WARNING", "Documents", "Document file is empty", file=doc.file))

                # Check images and media assets
                img_matches = re.findall(r"!\[(.*?)\]\((.*?)\)", content)
                for alt, img_path in img_matches:
                    clean_path = img_path.split("?")[0].split("#")[0]
                    ext = Path(clean_path).suffix.lower()
                    if ext in (".mp4", ".webm", ".ogg", ".ogv", ".mov"):
                        stats["videos"] += 1
                    else:
                        stats["images"] += 1

                    if not re.match(r"^https?://", clean_path, re.IGNORECASE) and not clean_path.startswith("data:"):
                        c1 = (doc_file.parent / clean_path).resolve()
                        c2 = (self.assets_path / clean_path).resolve()
                        c3 = (self.assets_path / Path(clean_path).name).resolve()
                        if not any(c.is_file() for c in (c1, c2, c3)):
                            issues.append(
                                ValidationIssue(
                                    "WARNING",
                                    "Assets",
                                    f"Referenced image/media asset not found on disk: '{clean_path}'",
                                    file=doc.file,
                                )
                            )

                # Check markdown video links: [label](path.mp4)
                video_link_matches = re.findall(
                    r"(?<!\!)\[(.*?)\]\(([^)]+?\.(?:mp4|webm|ogg|ogv|mov)(?:[?#][^)]*)?)\)",
                    content,
                    re.IGNORECASE,
                )
                for label, vid_path in video_link_matches:
                    stats["videos"] += 1
                    clean_path = vid_path.split("?")[0].split("#")[0]
                    if not re.match(r"^https?://", clean_path, re.IGNORECASE) and not clean_path.startswith("data:"):
                        c1 = (doc_file.parent / clean_path).resolve()
                        c2 = (self.assets_path / clean_path).resolve()
                        c3 = (self.assets_path / Path(clean_path).name).resolve()
                        if not any(c.is_file() for c in (c1, c2, c3)):
                            issues.append(
                                ValidationIssue(
                                    "WARNING",
                                    "Assets",
                                    f"Referenced video asset not found on disk: '{clean_path}'",
                                    file=doc.file,
                                )
                            )

                # Check HTML media tags: <img ...>, <video ...>, <source ...>
                html_media_matches = re.findall(
                    r'<(img|video|source)\b[^>]*?\bsrc=["\']([^"\']+)["\']',
                    content,
                    re.IGNORECASE,
                )
                for tag_name, src_path in html_media_matches:
                    clean_path = src_path.split("?")[0].split("#")[0]
                    ext = Path(clean_path).suffix.lower()
                    if tag_name.lower() in ("video", "source") or ext in (".mp4", ".webm", ".ogg", ".ogv", ".mov"):
                        stats["videos"] += 1
                    else:
                        stats["images"] += 1

                    if not re.match(r"^https?://", clean_path, re.IGNORECASE) and not clean_path.startswith("data:"):
                        c1 = (doc_file.parent / clean_path).resolve()
                        c2 = (self.assets_path / clean_path).resolve()
                        c3 = (self.assets_path / Path(clean_path).name).resolve()
                        if not any(c.is_file() for c in (c1, c2, c3)):
                            issues.append(
                                ValidationIssue(
                                    "WARNING",
                                    "Assets",
                                    f"Referenced HTML media asset not found on disk: '{clean_path}'",
                                    file=doc.file,
                                )
                            )

                # Basic Mermaid diagram validation
                self._validate_mermaid_blocks(content, doc.file, issues)

            except Exception as e:
                issues.append(ValidationIssue("ERROR", "Documents", f"Could not read document: {e}", file=doc.file))

        is_valid = len([i for i in issues if i.level == "ERROR"]) == 0
        return ValidationReport(is_valid=is_valid, issues=issues, stats=stats)

    def _validate_mermaid_blocks(self, content: str, file_name: str, issues: List[ValidationIssue]) -> None:
        """Checks for common Mermaid syntax pitfalls like unquoted parentheses in node text."""
        mermaid_blocks = re.findall(r"```mermaid\s+(.*?)```", content, re.DOTALL)
        for block in mermaid_blocks:
            lines = block.splitlines()
            for line_no, line in enumerate(lines, 1):
                # Pattern: id[text with (parens) without quotes]
                if re.search(r"\[[^\"'\n]*\([^\)\n]+\)[^\"'\n]*\]", line):
                    issues.append(
                        ValidationIssue(
                            "WARNING",
                            "Mermaid",
                            f"Mermaid node label with parentheses should be enclosed in quotes: `{line.strip()}`",
                            file=file_name,
                            line=line_no,
                        )
                    )
