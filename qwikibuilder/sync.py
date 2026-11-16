"""
Live synchronization, feedback retrieval, diffing, and optimistic concurrency
state management for Qwiki Builder.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Tuple

from .client import QwikiClient
from .manifest import CategoryItem, DocumentItem, QwikiProjectManifest


def sha256_text(text: str) -> str:
    """Computes hex SHA-256 of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SyncManager:
    """
    Manages .qwiki-sync state (remote SHA-256 baselines, 3-way merge bases,
    and sidecar Comment/Talk feedback digests) for live-published Qwiki chapters.
    """

    SYNC_DIR_NAME = ".qwiki-sync"

    def __init__(self, manifest: QwikiProjectManifest, client: QwikiClient):
        self.manifest = manifest
        self.client = client
        self.project_root = (manifest.project_root or Path.cwd()).resolve()
        self.docs_path = manifest.get_docs_path()
        self.sync_dir = self.project_root / self.SYNC_DIR_NAME
        self.base_dir = self.sync_dir / "base"
        self.feedback_dir = self.sync_dir / "feedback"
        self.conflicts_dir = self.sync_dir / "conflicts"
        self.state_file = self.sync_dir / "state.json"

    def load_state(self) -> Dict[str, Dict[str, Any]]:
        """Loads persisted remote sync baselines from .qwiki-sync/state.json."""
        if not self.state_file.is_file():
            return {}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def save_state(self, state: Dict[str, Dict[str, Any]]) -> None:
        """Atomically writes sync state to .qwiki-sync/state.json."""
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def get_expected_sha256(self, slug: str) -> Optional[str]:
        """Returns the last-known remote SHA-256 for a slug, if tracked."""
        entry = self.load_state().get(slug)
        if isinstance(entry, dict):
            sha = entry.get("sha256")
            if isinstance(sha, str) and sha:
                return sha
        return None

    def _base_file_path(self, book_id: str, slug: str, doc_type: str) -> Path:
        ext = ".html" if doc_type == "html" else ".md"
        safe_book = "".join(c if c.isalnum() or c in "-_" else "_" for c in (book_id or "general"))
        safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
        return self.base_dir / f"{safe_book}__{safe_slug}{ext}"

    def _conflict_file_path(self, book_id: str, slug: str, doc_type: str) -> Path:
        ext = ".html" if doc_type == "html" else ".md"
        safe_book = "".join(c if c.isalnum() or c in "-_" else "_" for c in (book_id or "general"))
        safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
        return self.conflicts_dir / f"{safe_book}__{safe_slug}.remote{ext}"

    def _feedback_paths(self, book_id: str, slug: str) -> Tuple[Path, Path]:
        safe_book = "".join(c if c.isalnum() or c in "-_" else "_" for c in (book_id or "general"))
        safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
        return (
            self.feedback_dir / f"{safe_book}__{safe_slug}.feedback.md",
            self.feedback_dir / f"{safe_book}__{safe_slug}.feedback.json",
        )

    def record_synced_baseline(
        self,
        slug: str,
        book_id: str,
        doc_type: str,
        remote_sha256: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Persists remote SHA-256 and base content snapshot after a pull or push."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        base_file = self._base_file_path(book_id, slug, doc_type)
        base_file.write_text(content, encoding="utf-8")

        state = self.load_state()
        meta = meta or {}
        state[slug] = {
            "slug": slug,
            "bookId": book_id,
            "type": doc_type,
            "docId": meta.get("docId", state.get(slug, {}).get("docId", "")),
            "shareKey": meta.get("shareKey", state.get(slug, {}).get("shareKey", "")),
            "status": meta.get("status", state.get(slug, {}).get("status", "")),
            "title": meta.get("title", state.get(slug, {}).get("title", "")),
            "sha256": remote_sha256,
            "dateModified": meta.get("dateModified", ""),
            "syncedAt": datetime.now(timezone.utc).isoformat(),
            "baseFile": str(base_file.relative_to(self.project_root)),
        }
        self.save_state(state)

    def resolve_local_doc_path(self, doc: Optional[DocumentItem], remote_doc: Dict[str, Any]) -> Path:
        """Resolves the local filesystem path for a manifest or remote-only document."""
        if doc is not None:
            cand_docs = (self.docs_path / doc.file).resolve()
            if cand_docs.is_file():
                return cand_docs
            cand_root = (self.project_root / doc.file).resolve()
            if cand_root.is_file():
                return cand_root
            return cand_docs

        book_id = remote_doc.get("bookId") or "general"
        slug = remote_doc.get("slug") or "document"
        ext = ".html" if remote_doc.get("type") == "html" else ".md"
        return (self.docs_path / book_id / f"{slug}{ext}").resolve()

    def write_feedback_sidecars(self, remote_doc: Dict[str, Any]) -> Tuple[Path, Path]:
        """Writes live Comments, Talk Page topics, lock state, and metadata into .qwiki-sync/feedback/."""
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        book_id = remote_doc.get("bookId") or "general"
        slug = remote_doc.get("slug") or "unknown"
        md_path, json_path = self._feedback_paths(book_id, slug)

        json_payload = {
            "docId": remote_doc.get("docId", ""),
            "bookId": book_id,
            "slug": slug,
            "title": remote_doc.get("title", ""),
            "status": remote_doc.get("status", ""),
            "shareKey": remote_doc.get("shareKey", ""),
            "sha256": remote_doc.get("sha256", ""),
            "dateModified": remote_doc.get("dateModified", ""),
            "lock": remote_doc.get("lock", {}),
            "commentsEnabled": remote_doc.get("commentsEnabled", False),
            "commentsCount": remote_doc.get("commentsCount", 0),
            "comments": remote_doc.get("comments", []),
            "talkEnabled": remote_doc.get("talkEnabled", False),
            "talkTopicsCount": remote_doc.get("talkTopicsCount", 0),
            "talkTopics": remote_doc.get("talkTopics", []),
            "talkRaw": remote_doc.get("talkRaw", ""),
        }
        json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        lines: List[str] = [
            f"# Live Feedback & State: {remote_doc.get('title') or slug}",
            "",
            f"- **Category / Slug:** `{book_id}/{slug}`",
            f"- **Status:** `{remote_doc.get('status', 'unknown')}`",
            f"- **Share Key:** `{remote_doc.get('shareKey') or 'none'}`",
            f"- **Remote SHA-256:** `{remote_doc.get('sha256', '')}`",
            f"- **Last Modified:** `{remote_doc.get('dateModified', '')}`",
        ]
        lock = remote_doc.get("lock") or {}
        if lock.get("locked"):
            lines.append(
                f"- **ACTIVE EDITOR LOCK:** Locked by `{lock.get('user', 'unknown')}` "
                f"(expires in {lock.get('expiresIn', 0)}s)"
            )
        else:
            lines.append("- **Editor Lock:** Unlocked")

        lines.extend(["", "## Comments (`tool-comments`)", ""])
        comments = remote_doc.get("comments") or []
        if not comments:
            lines.append("*No comments recorded.*")
        else:
            for c in comments:
                author = c.get("author", "unknown")
                role = c.get("role", "viewer")
                created = c.get("createdAt", "")
                if c.get("isDeleted"):
                    lines.append(f"### @{author} ({role}) - {created}")
                    lines.append("*[Deleted]*")
                else:
                    lines.append(f"### @{author} ({role}) - {created}")
                    lines.append((c.get("content") or "").strip())
                for rep in c.get("replies") or []:
                    r_author = rep.get("author", "unknown")
                    r_role = rep.get("role", "viewer")
                    r_created = rep.get("createdAt", "")
                    lines.append(f"> **Reply by @{r_author} ({r_role}) - {r_created}:**")
                    if rep.get("isDeleted"):
                        lines.append("> *[Deleted]*")
                    else:
                        for rline in (rep.get("content") or "").strip().splitlines():
                            lines.append(f"> {rline}")
                lines.append("")

        lines.extend(["", "## Editorial Talk Page (`tool-talk`)", ""])
        talk_raw = (remote_doc.get("talkRaw") or "").strip()
        talk_topics = remote_doc.get("talkTopics") or []
        if talk_raw:
            lines.append(talk_raw)
        elif talk_topics:
            for topic in talk_topics:
                lines.append(f"### {topic.get('title', 'Topic')}")
                lines.append((topic.get("rawMarkdown") or "").strip())
                lines.append("")
        else:
            lines.append("*No Talk Page topics recorded.*")

        md_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return md_path, json_path

    def _try_diff3_merge(self, local_text: str, base_text: str, remote_text: str) -> Tuple[bool, Optional[str]]:
        """Attempts a clean 3-way merge using system diff3 if installed."""
        diff3_bin = shutil.which("diff3")
        if not diff3_bin:
            return False, None
        with TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            p_local = tmp / "local.txt"
            p_base = tmp / "base.txt"
            p_remote = tmp / "remote.txt"
            p_local.write_text(local_text, encoding="utf-8")
            p_base.write_text(base_text, encoding="utf-8")
            p_remote.write_text(remote_text, encoding="utf-8")
            proc = subprocess.run(
                [diff3_bin, "-m", str(p_local), str(p_base), str(p_remote)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                return True, proc.stdout
            return False, proc.stdout

    def diff_document(self, slug: str, doc: Optional[DocumentItem] = None) -> Dict[str, Any]:
        """Fetches remote state and computes unified diff + metadata/feedback summary without modifying local files."""
        remote_doc = self.client.get_document(
            slug=slug,
            share_key=doc.share_key if doc else None,
            book_id=doc.category if doc else None,
            include_comments=True,
            include_talk=True,
        )
        local_path = self.resolve_local_doc_path(doc, remote_doc)
        local_content = local_path.read_text(encoding="utf-8") if local_path.is_file() else ""
        remote_content = remote_doc.get("content", "")

        diff_lines = list(
            difflib.unified_diff(
                local_content.splitlines(keepends=True),
                remote_content.splitlines(keepends=True),
                fromfile=f"local:{local_path.name}",
                tofile=f"remote:{remote_doc.get('bookId', '')}/{remote_doc.get('slug', slug)}",
            )
        )

        meta_diffs: List[Tuple[str, Any, Any]] = []
        if doc is not None:
            checks = [
                ("title", doc.title, remote_doc.get("title", "")),
                ("status", doc.status, remote_doc.get("status", "")),
                ("description", doc.description, remote_doc.get("description", "")),
                ("category", doc.category, remote_doc.get("bookId", "")),
                ("share_key", doc.share_key or "", remote_doc.get("shareKey", "")),
            ]
            for field_name, loc_val, rem_val in checks:
                if loc_val != rem_val and (loc_val or rem_val):
                    meta_diffs.append((field_name, loc_val, rem_val))

        return {
            "remote_doc": remote_doc,
            "local_path": local_path,
            "local_exists": local_path.is_file(),
            "content_changed": local_content != remote_content,
            "diff_text": "".join(diff_lines),
            "meta_diffs": meta_diffs,
            "lock": remote_doc.get("lock") or {},
            "comments_count": remote_doc.get("commentsCount", 0),
            "talk_topics_count": remote_doc.get("talkTopicsCount", 0),
            "tracked_sha256": self.get_expected_sha256(remote_doc.get("slug", slug)),
            "remote_sha256": remote_doc.get("sha256", ""),
        }

    def pull_document(
        self,
        slug: str,
        doc: Optional[DocumentItem] = None,
        overwrite: bool = False,
        sync_meta: bool = False,
    ) -> Dict[str, Any]:
        """
        Downloads a published document + comments + talk page, performs safe 3-way
        reconciliation against local files, writes feedback sidecars, and records
        the remote SHA-256 baseline.
        """
        remote_doc = self.client.get_document(
            slug=slug,
            share_key=doc.share_key if doc else None,
            book_id=doc.category if doc else None,
            include_comments=True,
            include_talk=True,
        )

        resolved_slug = remote_doc.get("slug") or slug
        book_id = remote_doc.get("bookId") or (doc.category if doc else "general")
        doc_type = remote_doc.get("type") or (doc.doc_type if doc else "markdown")
        remote_content = remote_doc.get("content", "")
        remote_sha256 = remote_doc.get("sha256") or sha256_text(remote_content)

        feedback_md, feedback_json = self.write_feedback_sidecars(remote_doc)
        local_path = self.resolve_local_doc_path(doc, remote_doc)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        base_file = self._base_file_path(book_id, resolved_slug, doc_type)
        base_content = base_file.read_text(encoding="utf-8") if base_file.is_file() else None

        outcome = "up_to_date"
        conflict_path: Optional[Path] = None

        if not local_path.is_file():
            local_path.write_text(remote_content, encoding="utf-8")
            outcome = "created"
        else:
            local_content = local_path.read_text(encoding="utf-8")
            if local_content == remote_content:
                outcome = "up_to_date"
            elif overwrite or (base_content is not None and local_content == base_content):
                local_path.write_text(remote_content, encoding="utf-8")
                outcome = "updated"
            elif base_content is not None:
                merged_ok, merged_text = self._try_diff3_merge(local_content, base_content, remote_content)
                if merged_ok and merged_text is not None:
                    local_path.write_text(merged_text, encoding="utf-8")
                    outcome = "merged"
                else:
                    self.conflicts_dir.mkdir(parents=True, exist_ok=True)
                    conflict_path = self._conflict_file_path(book_id, resolved_slug, doc_type)
                    conflict_path.write_text(remote_content, encoding="utf-8")
                    outcome = "conflict"
            else:
                # No common base and local != remote: preserve both without clobbering
                self.conflicts_dir.mkdir(parents=True, exist_ok=True)
                conflict_path = self._conflict_file_path(book_id, resolved_slug, doc_type)
                conflict_path.write_text(remote_content, encoding="utf-8")
                outcome = "conflict"

        if outcome != "conflict":
            self.record_synced_baseline(
                slug=resolved_slug,
                book_id=book_id,
                doc_type=doc_type,
                remote_sha256=remote_sha256,
                content=remote_content,
                meta=remote_doc,
            )

        manifest_updated = False
        if doc is not None:
            if not doc.share_key and remote_doc.get("shareKey"):
                doc.share_key = remote_doc["shareKey"]
                manifest_updated = True
            if sync_meta:
                if remote_doc.get("title") and doc.title != remote_doc["title"]:
                    doc.title = remote_doc["title"]
                    manifest_updated = True
                if remote_doc.get("status") and doc.status != remote_doc["status"]:
                    doc.status = remote_doc["status"]
                    manifest_updated = True
                if remote_doc.get("description") is not None and doc.description != remote_doc["description"]:
                    doc.description = remote_doc["description"]
                    manifest_updated = True
        elif sync_meta:
            # Register newly discovered remote chapter into manifest
            if not any(c.id == book_id for c in self.manifest.categories):
                self.manifest.categories.append(
                    CategoryItem(id=book_id, title=book_id.replace("-", " ").title())
                )
            try:
                rel_file = str(local_path.relative_to(self.docs_path))
            except ValueError:
                rel_file = local_path.name
            self.manifest.documents.append(
                DocumentItem(
                    file=rel_file,
                    category=book_id,
                    slug=resolved_slug,
                    title=remote_doc.get("title") or resolved_slug,
                    status=remote_doc.get("status") or "published",
                    description=remote_doc.get("description") or "",
                    doc_type=doc_type,
                    share_key=remote_doc.get("shareKey") or None,
                    public_shareable=bool(remote_doc.get("publicShareable", True)),
                )
            )
            manifest_updated = True

        if manifest_updated and self.manifest.project_root:
            manifest_path = self.manifest.project_root / "qwiki-project.json"
            if manifest_path.is_file():
                self.manifest.save(manifest_path)

        return {
            "outcome": outcome,
            "slug": resolved_slug,
            "bookId": book_id,
            "local_path": local_path,
            "conflict_path": conflict_path,
            "feedback_md": feedback_md,
            "feedback_json": feedback_json,
            "remote_sha256": remote_sha256,
            "comments_count": remote_doc.get("commentsCount", 0),
            "talk_topics_count": remote_doc.get("talkTopicsCount", 0),
            "lock": remote_doc.get("lock") or {},
            "manifest_updated": manifest_updated,
            "fallback_llm_api": bool(remote_doc.get("_fallback_llm_api")),
        }
