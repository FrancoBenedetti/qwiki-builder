"""
Project Manifest model and auto-discovery engine for Qwiki documentation suites.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def slugify(text: str) -> str:
    """Converts a string into a clean URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def extract_title_from_markdown(content: str, default: str) -> str:
    """Extracts first H1 title from Markdown text, or returns default."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# ") and len(line) > 2:
            return line[2:].strip()
    return default


def extract_title_from_html(content: str, default: str) -> str:
    """Extracts title from <title> or <h1> tag in HTML text, or returns default."""
    m_h1 = re.search(r"<h1[^>]*>(.*?)</h1>", content, re.IGNORECASE | re.DOTALL)
    if m_h1:
        clean = re.sub(r"<[^>]+>", "", m_h1.group(1)).strip()
        if clean:
            return clean
    m_title = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
    if m_title:
        clean = re.sub(r"<[^>]+>", "", m_title.group(1)).strip()
        if clean:
            return clean
    return default


@dataclass
class CategoryItem:
    id: str
    title: str
    description: str = ""
    parent: Optional[str] = None
    order: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CategoryItem:
        return cls(
            id=str(data.get("id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            description=str(data.get("description", "")).strip(),
            parent=data.get("parent"),
            order=int(data.get("order", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
        }
        if self.description:
            d["description"] = self.description
        if self.parent:
            d["parent"] = self.parent
        if self.order:
            d["order"] = self.order
        return d


@dataclass
class DocumentItem:
    file: str  # Relative to project directory or docs_dir
    category: str
    slug: str
    title: str
    status: str = "published"
    description: str = ""
    doc_type: str = "markdown"  # 'markdown' or 'html'
    share_key: Optional[str] = None
    public_shareable: bool = True
    order: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentItem:
        return cls(
            file=str(data.get("file", "")).strip(),
            category=str(data.get("category", "")).strip(),
            slug=str(data.get("slug", "")).strip(),
            title=str(data.get("title", "")).strip(),
            status=str(data.get("status", "published")).strip().lower(),
            description=str(data.get("description", "")).strip(),
            doc_type=str(data.get("type", data.get("doc_type", "markdown"))).strip().lower(),
            share_key=data.get("share_key") or data.get("shareKey"),
            public_shareable=bool(data.get("public_shareable", data.get("publicShareable", True))),
            order=int(data.get("order", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "file": self.file,
            "category": self.category,
            "slug": self.slug,
            "title": self.title,
            "type": self.doc_type,
            "status": self.status,
        }
        if self.description:
            d["description"] = self.description
        if self.share_key:
            d["share_key"] = self.share_key
        if not self.public_shareable:
            d["public_shareable"] = False
        if self.order:
            d["order"] = self.order
        return d


@dataclass
class QwikiProjectManifest:
    name: str = "Online Documentation"
    slug: str = "online-docs"
    version: str = "1.0.0"
    doc_type_preset: str = "user-guide"  # user-guide, equipment-manual, quality-manual, safety-handbook, sop, custom
    description: str = ""
    wiki_url: Optional[str] = None
    api_key: Optional[str] = None
    profile: Optional[str] = None
    docs_dir: str = "docs"
    assets_dir: str = "docs/assets"
    default_status: str = "published"
    public_shareable: bool = True
    categories: List[CategoryItem] = field(default_factory=list)
    documents: List[DocumentItem] = field(default_factory=list)
    project_root: Optional[Path] = None

    @classmethod
    def find_manifest_file(cls, start_dir: Optional[Path] = None) -> Optional[Path]:
        """Looks for qwiki-project.json starting in start_dir and walking upwards."""
        cur = (start_dir or Path.cwd()).resolve()
        candidates = ["qwiki-project.json", "qwiki.project.json", "qwiki.json"]
        while True:
            for name in candidates:
                cand = cur / name
                if cand.is_file():
                    return cand
            if cur.parent == cur:
                break
            cur = cur.parent
        return None

    @classmethod
    def load(cls, manifest_path: Path) -> QwikiProjectManifest:
        """Loads and parses a qwiki-project.json file."""
        manifest_path = manifest_path.resolve()
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifest file not found: {manifest_path}")

        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        categories = [CategoryItem.from_dict(c) for c in raw.get("categories", [])]
        documents = [DocumentItem.from_dict(d) for d in raw.get("documents", [])]

        manifest = cls(
            name=raw.get("name", "Online Documentation"),
            slug=raw.get("slug", "online-docs"),
            version=raw.get("version", "1.0.0"),
            doc_type_preset=raw.get("doc_type_preset", raw.get("type", "user-guide")),
            description=raw.get("description", ""),
            wiki_url=raw.get("wiki_url") or raw.get("url"),
            api_key=raw.get("api_key") or raw.get("apiKey"),
            profile=raw.get("profile"),
            docs_dir=raw.get("docs_dir", "docs"),
            assets_dir=raw.get("assets_dir", "docs/assets"),
            default_status=raw.get("default_status", "published"),
            public_shareable=bool(raw.get("public_shareable", True)),
            categories=categories,
            documents=documents,
            project_root=manifest_path.parent,
        )

        # If no documents are declared, run auto-discovery
        if not manifest.documents:
            manifest.auto_discover()

        return manifest

    def save(self, destination_path: Optional[Path] = None) -> Path:
        """Saves current manifest state to JSON."""
        target = destination_path or (self.project_root / "qwiki-project.json" if self.project_root else Path("qwiki-project.json"))
        target = target.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        data: Dict[str, Any] = {
            "name": self.name,
            "slug": self.slug,
            "version": self.version,
            "doc_type_preset": self.doc_type_preset,
            "description": self.description,
            "docs_dir": self.docs_dir,
            "assets_dir": self.assets_dir,
            "default_status": self.default_status,
            "public_shareable": self.public_shareable,
        }
        if self.profile:
            data["profile"] = self.profile
        if self.wiki_url:
            data["wiki_url"] = self.wiki_url
        if self.api_key:
            data["api_key"] = self.api_key

        data["categories"] = [c.to_dict() for c in self.categories]
        data["documents"] = [d.to_dict() for d in self.documents]

        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return target

    def get_docs_path(self) -> Path:
        """Resolves absolute path to docs directory."""
        root = self.project_root or Path.cwd()
        return (root / self.docs_dir).resolve()

    def get_assets_path(self) -> Path:
        """Resolves absolute path to assets directory."""
        root = self.project_root or Path.cwd()
        return (root / self.assets_dir).resolve()

    def auto_discover(self) -> None:
        """
        Scans docs_dir and automatically creates CategoryItem and DocumentItem entries
        for all discovered .md and .html files based on directory organization.
        """
        docs_path = self.get_docs_path()
        if not docs_path.is_dir():
            return

        cat_map: Dict[str, CategoryItem] = {c.id: c for c in self.categories}
        discovered_docs: List[DocumentItem] = []

        all_files = sorted(list(docs_path.rglob("*.md")) + list(docs_path.rglob("*.html")))

        for fpath in all_files:
            # Skip templates or hidden files
            if any(part.startswith(".") for part in fpath.parts):
                continue
            if "assets" in fpath.parts:
                continue

            rel = fpath.relative_to(docs_path)
            content = fpath.read_text(encoding="utf-8")

            # Determine category
            if len(rel.parts) > 1:
                # Subfolder is category
                cat_id = rel.parts[0]
            else:
                cat_id = "general"

            if cat_id not in cat_map:
                cat_title = cat_id.replace("-", " ").replace("_", " ").title()
                new_cat = CategoryItem(id=cat_id, title=cat_title)
                cat_map[cat_id] = new_cat

            # Title & Slug
            is_html = fpath.suffix.lower() in (".html", ".htm")
            doc_type = "html" if is_html else "markdown"
            default_title = fpath.stem.replace("-", " ").replace("_", " ").title()

            if is_html:
                title = extract_title_from_html(content, default_title)
            else:
                title = extract_title_from_markdown(content, default_title)

            clean_slug = slugify(fpath.stem)
            if not clean_slug:
                clean_slug = f"doc-{slugify(title)}"

            doc_item = DocumentItem(
                file=str(rel),
                category=cat_id,
                slug=clean_slug,
                title=title,
                status=self.default_status,
                doc_type=doc_type,
                public_shareable=self.public_shareable,
            )
            discovered_docs.append(doc_item)

        self.categories = list(cat_map.values())
        self.documents = discovered_docs
