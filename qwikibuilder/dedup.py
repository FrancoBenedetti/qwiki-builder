"""
Deduplication and remote cleanup engine for Standalone Qwiki.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from .client import QwikiClient
from .manifest import QwikiProjectManifest


class QwikiDeduplicator:
    """Detects and resolves duplicate remote chapters and numerical slug suffixes."""

    def __init__(self, client: QwikiClient, manifest: Optional[QwikiProjectManifest] = None):
        self.client = client
        self.manifest = manifest

    def analyze(self, book_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyzes remote chapters and returns a diagnostic report with identified duplicates.
        """
        chapters = self.client.list_chapters(book_id)
        canonical_slugs: Set[str] = set()
        if self.manifest:
            canonical_slugs = {d.slug for d in self.manifest.documents}

        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for ch in chapters:
            by_category.setdefault(ch.get("bookId", "unknown"), []).append(ch)

        duplicates: List[Dict[str, Any]] = []

        for cat_id, cat_chapters in by_category.items():
            seen_titles: Dict[str, Dict[str, Any]] = {}
            for ch in cat_chapters:
                slug = ch.get("slug", "")
                title = ch.get("title", "")
                is_duplicate = False
                reason = ""

                # 1. Check for numerical suffix (e.g., -1, -2, -3) when base slug exists or is canonical
                match_suffix = re.match(r"^(.*?)-(\d+)$", slug)
                if match_suffix:
                    base_slug = match_suffix.group(1)
                    if base_slug in canonical_slugs or any(c.get("slug") == base_slug for c in cat_chapters):
                        is_duplicate = True
                        reason = f"Numerical suffix of canonical base '{base_slug}'"

                # 2. Check for duplicate title in the same category
                if not is_duplicate and title in seen_titles:
                    prev = seen_titles[title]
                    is_duplicate = True
                    reason = f"Duplicate title of chapter '{prev.get('slug')}'"

                if is_duplicate:
                    duplicates.append({
                        "bookId": cat_id,
                        "slug": slug,
                        "title": title,
                        "shareKey": ch.get("shareKey"),
                        "reason": reason,
                    })
                else:
                    seen_titles[title] = ch

        return {
            "total_remote_chapters": len(chapters),
            "duplicates": duplicates,
            "duplicate_count": len(duplicates),
        }

    def remove_duplicates(self, dry_run: bool = False, book_id: Optional[str] = None) -> Tuple[int, int]:
        """
        Removes detected duplicate chapters from Qwiki.
        Returns (deleted_count, failed_count).
        """
        analysis = self.analyze(book_id)
        duplicates = analysis["duplicates"]

        deleted_count = 0
        failed_count = 0

        for dup in duplicates:
            slug = dup["slug"]
            cat_id = dup["bookId"]
            if dry_run:
                print(f"  [DRY-RUN] Would delete: [{cat_id}] {slug} ({dup['reason']})")
                deleted_count += 1
                continue

            try:
                res = self.client.delete_chapter(slug, cat_id)
                if res.get("success"):
                    print(f"  🗑️ Deleted duplicate: [{cat_id}] {slug}")
                    deleted_count += 1
                else:
                    print(f"  ⚠️ Failed deleting {slug}: {res.get('error')}")
                    failed_count += 1
            except Exception as e:
                print(f"  ❌ Error deleting {slug}: {e}")
                failed_count += 1

        return deleted_count, failed_count
