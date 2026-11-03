"""
Hyperlink resolution and category-path rewriting engine for Qwiki Builder.
Ensures internal Markdown and HTML cross-links point to canonical '<category>/<slug>' paths.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .manifest import DocumentItem, QwikiProjectManifest


class LinkManager:
    """
    Resolves relative Markdown and HTML hyperlinks between documents in a Qwiki documentation suite,
    rewriting them to canonical '<category>/<slug>' format so that Qwiki routing works seamlessly.
    """

    def __init__(self, manifest: QwikiProjectManifest):
        self.manifest = manifest
        self.docs_path = manifest.get_docs_path()
        self.project_root = manifest.project_root or Path.cwd()

        # Build lookup tables
        self.doc_by_alias: Dict[str, DocumentItem] = {}
        self.doc_by_canonical_path: Dict[Path, DocumentItem] = {}
        self._build_index()

    def _build_index(self) -> None:
        for doc in self.manifest.documents:
            target = f"{doc.category}/{doc.slug}"

            # Map by slug
            self.doc_by_alias[doc.slug.lower()] = doc
            self.doc_by_alias[f"{doc.slug.lower()}.md"] = doc
            self.doc_by_alias[f"{doc.slug.lower()}.html"] = doc

            # Map by category/slug
            self.doc_by_alias[target.lower()] = doc
            self.doc_by_alias[f"{target.lower()}.md"] = doc
            self.doc_by_alias[f"{target.lower()}.html"] = doc

            # Map by file name and path
            f_path = Path(doc.file)
            self.doc_by_alias[f_path.name.lower()] = doc
            self.doc_by_alias[f_path.stem.lower()] = doc
            self.doc_by_alias[doc.file.lower()] = doc
            self.doc_by_alias[f"docs/{doc.file}".lower()] = doc

            # Absolute file path on disk
            doc_file = (self.docs_path / doc.file).resolve()
            self.doc_by_canonical_path[doc_file] = doc
            cand_root = (self.project_root / doc.file).resolve()
            self.doc_by_canonical_path[cand_root] = doc

    def resolve_target(self, link_path: str, doc_dir: Optional[Path] = None) -> Optional[str]:
        """
        Attempts to resolve an internal link target to canonical '<category>/<slug>'.
        Returns None if not an internal document link or not recognized.
        """
        raw_path = link_path.strip()

        # Skip external schemes, mailto, tel, javascript, data, and pure anchors
        if re.match(r"^(https?://|mailto:|tel:|javascript:|data:|#)", raw_path, re.IGNORECASE):
            return None

        # Split off query and fragment/anchor
        base_part = raw_path
        query = ""
        anchor = ""
        if "#" in base_part:
            base_part, anchor = base_part.split("#", 1)
            anchor = f"#{anchor}"
        if "?" in base_part:
            base_part, query = base_part.split("?", 1)
            query = f"?{query}"

        clean = base_part.strip().strip("/")
        if not clean:
            return None

        # 1. Direct alias lookup
        clean_lower = clean.lower()
        if clean_lower in self.doc_by_alias:
            doc = self.doc_by_alias[clean_lower]
            return f"{doc.category}/{doc.slug}{query}{anchor}"

        # 2. Check if clean path is relative to current doc_dir
        if doc_dir is not None:
            try:
                candidate = (doc_dir / clean).resolve()
                if candidate in self.doc_by_canonical_path:
                    doc = self.doc_by_canonical_path[candidate]
                    return f"{doc.category}/{doc.slug}{query}{anchor}"
                candidate_md = (doc_dir / f"{clean}.md").resolve()
                if candidate_md in self.doc_by_canonical_path:
                    doc = self.doc_by_canonical_path[candidate_md]
                    return f"{doc.category}/{doc.slug}{query}{anchor}"
            except Exception:
                pass

        # 3. Check relative to docs_path
        try:
            candidate_docs = (self.docs_path / clean).resolve()
            if candidate_docs in self.doc_by_canonical_path:
                doc = self.doc_by_canonical_path[candidate_docs]
                return f"{doc.category}/{doc.slug}{query}{anchor}"
            candidate_docs_md = (self.docs_path / f"{clean}.md").resolve()
            if candidate_docs_md in self.doc_by_canonical_path:
                doc = self.doc_by_canonical_path[candidate_docs_md]
                return f"{doc.category}/{doc.slug}{query}{anchor}"
        except Exception:
            pass

        return None

    def process_content_links(
        self,
        content: str,
        doc_dir: Optional[Path] = None,
    ) -> Tuple[str, List[Tuple[str, str]]]:
        """
        Rewrites internal Markdown and HTML hyperlinks to canonical '<category>/<slug>'.
        Leaves images and external links untouched.
        Returns (rewritten_content, list_of_rewrites).
        """
        rewrites: List[Tuple[str, str]] = []

        # Replace Markdown hyperlinks: [text](target)
        # Avoid matching image tags ![alt](img) via negative lookbehind (?<!!)
        def replace_md_link(match: re.Match) -> str:
            text = match.group(1)
            raw_target = match.group(2).strip()

            # Handle optional title inside parentheses, e.g. (url "title")
            title_part = ""
            target_url = raw_target
            title_match = re.search(r'^(.*?)\s+(".*?"|\'.*?\')\s*$', raw_target)
            if title_match:
                target_url = title_match.group(1).strip()
                title_part = " " + title_match.group(2)

            resolved = self.resolve_target(target_url, doc_dir=doc_dir)
            if resolved and resolved != target_url:
                rewrites.append((target_url, resolved))
                return f"[{text}]({resolved}{title_part})"
            return match.group(0)

        # Process Markdown links
        processed = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", replace_md_link, content)

        # Replace HTML hyperlinks: <a ... href="..." ...>
        def replace_html_link(match: re.Match) -> str:
            prefix = match.group(1)
            raw_target = match.group(2).strip()
            suffix = match.group(3)

            resolved = self.resolve_target(raw_target, doc_dir=doc_dir)
            if resolved and resolved != raw_target:
                rewrites.append((raw_target, resolved))
                return f"{prefix}{resolved}{suffix}"
            return match.group(0)

        processed = re.sub(
            r'(<a\b[^>]*?\bhref=["\'])([^"\']+)(["\'][^>]*?>)',
            replace_html_link,
            processed,
            flags=re.IGNORECASE,
        )

        return processed, rewrites
