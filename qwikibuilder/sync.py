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

    def get_expected_sha256(self, slug: str, doc_id: Optional[str] = None) -> Optional[str]:
        """Returns the last-known remote SHA-256 for a slug or doc_id, if tracked."""
        state = self.load_state()
        entry = state.get(slug)
        if not isinstance(entry, dict) and doc_id:
            for val in state.values():
                if isinstance(val, dict) and val.get("docId") == doc_id:
                    entry = val
                    break
        if isinstance(entry, dict):
            sha = entry.get("sha256")
            if isinstance(sha, str) and sha:
                return sha
        return None

    @staticmethod
    def _doc_ext(doc_type: str) -> str:
        if doc_type == "form":
            return ".form.json"
        if doc_type == "html":
            return ".html"
        return ".md"

    def _base_file_path(self, book_id: str, slug: str, doc_type: str) -> Path:
        ext = self._doc_ext(doc_type)
        safe_book = "".join(c if c.isalnum() or c in "-_" else "_" for c in (book_id or "general"))
        safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in slug)
        return self.base_dir / f"{safe_book}__{safe_slug}{ext}"

    def _conflict_file_path(self, book_id: str, slug: str, doc_type: str) -> Path:
        ext = self._doc_ext(doc_type)
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
        ext = self._doc_ext(remote_doc.get("type", "markdown"))
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
            doc_id=doc.doc_id if doc else None,
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
            loc_theme, _ = self.manifest.resolve_theme_ref(doc.theme)
            checks = [
                ("title", doc.title, remote_doc.get("title", "")),
                ("status", doc.status, remote_doc.get("status", "")),
                ("description", doc.description, remote_doc.get("description", "")),
                ("category", doc.category, remote_doc.get("bookId", "")),
                ("share_key", doc.share_key or "", remote_doc.get("shareKey", "")),
                ("theme", loc_theme or "", remote_doc.get("theme", "")),
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
            doc_id=doc.doc_id if doc else None,
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
            if not doc.doc_id and remote_doc.get("docId"):
                doc.doc_id = remote_doc["docId"]
                manifest_updated = True
            if not doc.share_key and remote_doc.get("shareKey"):
                doc.share_key = remote_doc["shareKey"]
                manifest_updated = True
            if sync_meta:
                if resolved_slug and doc.slug != resolved_slug:
                    doc.slug = resolved_slug
                    manifest_updated = True
                if book_id and doc.category != book_id:
                    old_path = self.resolve_local_doc_path(doc, remote_doc)
                    ext = self._doc_ext(doc_type)
                    new_path = (self.docs_path / book_id / f"{resolved_slug}{ext}").resolve()
                    if old_path.is_file() and old_path != new_path:
                        new_path.parent.mkdir(parents=True, exist_ok=True)
                        old_path.replace(new_path)
                        local_path = new_path
                    doc.category = book_id
                    try:
                        doc.file = str(new_path.relative_to(self.docs_path))
                    except ValueError:
                        doc.file = new_path.name
                    if not any(c.id == book_id for c in self.manifest.categories):
                        self.manifest.categories.append(
                            CategoryItem(id=book_id, title=book_id.replace("-", " ").title())
                        )
                    manifest_updated = True
                if remote_doc.get("title") and doc.title != remote_doc["title"]:
                    doc.title = remote_doc["title"]
                    manifest_updated = True
                if remote_doc.get("status") and doc.status != remote_doc["status"]:
                    doc.status = remote_doc["status"]
                    manifest_updated = True
                if remote_doc.get("description") is not None and doc.description != remote_doc["description"]:
                    doc.description = remote_doc["description"]
                    manifest_updated = True
                if remote_doc.get("theme") is not None:
                    rem_theme = remote_doc["theme"] or None
                    loc_theme, _ = self.manifest.resolve_theme_ref(doc.theme)
                    if loc_theme != rem_theme:
                        doc.theme = rem_theme
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
                    doc_id=remote_doc.get("docId") or None,
                    share_key=remote_doc.get("shareKey") or None,
                    public_shareable=bool(remote_doc.get("publicShareable", True)),
                    theme=remote_doc.get("theme") or None,
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
            "docId": remote_doc.get("docId", ""),
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

    def match_local_document(self, remote_chapter: Dict[str, Any]) -> Optional[DocumentItem]:
        """
        Matches a remote chapter dictionary against local manifest documents,
        preferring immutable docId, then shareKey, then slug.
        """
        r_doc_id = (remote_chapter.get("docId") or "").strip()
        r_share_key = (remote_chapter.get("shareKey") or "").strip()
        r_slug = (remote_chapter.get("slug") or "").strip()

        if r_doc_id:
            for d in self.manifest.documents:
                if d.doc_id and d.doc_id == r_doc_id:
                    return d
            # Also check tracked state.json for docId -> slug mapping
            state = self.load_state()
            for tracked_slug, st in state.items():
                if isinstance(st, dict) and st.get("docId") == r_doc_id:
                    for d in self.manifest.documents:
                        if d.slug == tracked_slug:
                            return d

        if r_share_key:
            for d in self.manifest.documents:
                if d.share_key and d.share_key == r_share_key:
                    return d

        if r_slug:
            for d in self.manifest.documents:
                if d.slug == r_slug:
                    return d
        return None

    def compute_tree_status(self, book_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Compares the live remote Qwiki tree against local manifest and .qwiki-sync baselines.
        Identifies:
          - remote_only_categories: Categories created on live wiki not in qwiki-project.json
          - local_only_categories: Categories in qwiki-project.json not on live wiki
          - remote_only_docs: Pages created on live wiki not in qwiki-project.json
          - remote_deleted_docs: Pages previously synced (in state.json) that were deleted on live wiki
          - local_new_docs: Pages in qwiki-project.json never synced and not on live wiki
          - modified_docs: Pages present on both sides with local, remote, or both content/meta changes
          - in_sync_docs: Pages identical on both sides
        """
        tree = self.client.get_tree(book_id=book_id)
        remote_cats: List[Dict[str, Any]] = tree.get("categories", [])
        remote_chaps: List[Dict[str, Any]] = tree.get("chapters", [])
        state = self.load_state()

        local_cat_map = {c.id: c for c in self.manifest.categories}
        remote_cat_map = {c.get("id"): c for c in remote_cats if c.get("id")}

        remote_only_categories = [rc for cid, rc in remote_cat_map.items() if cid not in local_cat_map]
        local_only_categories = [
            lc for cid, lc in local_cat_map.items()
            if cid not in remote_cat_map and (not book_id or cid == book_id)
        ]

        matched_local_docs: set[int] = set()
        remote_only_docs: List[Dict[str, Any]] = []
        modified_docs: List[Dict[str, Any]] = []
        in_sync_docs: List[Dict[str, Any]] = []

        for rch in remote_chaps:
            doc = self.match_local_document(rch)
            if doc is None:
                remote_only_docs.append(rch)
                continue

            matched_local_docs.add(id(doc))
            local_path = self.resolve_local_doc_path(doc, rch)
            local_exists = local_path.is_file()
            local_sha = sha256_text(local_path.read_text(encoding="utf-8")) if local_exists else ""
            remote_sha = rch.get("sha256") or ""
            tracked_sha = self.get_expected_sha256(doc.slug, doc.doc_id or rch.get("docId"))

            local_changed = bool(tracked_sha and local_sha and local_sha != tracked_sha)
            remote_changed = bool(tracked_sha and remote_sha and remote_sha != tracked_sha)
            if not tracked_sha and local_sha and remote_sha:
                content_diff = local_sha != remote_sha
            else:
                content_diff = (local_sha != remote_sha) if (local_sha and remote_sha) else (not local_exists)

            moved_or_renamed = (
                (rch.get("slug") and doc.slug != rch.get("slug"))
                or (rch.get("bookId") and doc.category != rch.get("bookId"))
            )
            title_changed = bool(rch.get("title") and doc.title != rch.get("title"))
            status_changed = bool(rch.get("status") and doc.status != rch.get("status"))

            if content_diff or moved_or_renamed or title_changed or status_changed or not local_exists:
                modified_docs.append({
                    "doc": doc,
                    "remote": rch,
                    "local_path": local_path,
                    "local_exists": local_exists,
                    "local_sha256": local_sha,
                    "remote_sha256": remote_sha,
                    "tracked_sha256": tracked_sha,
                    "local_changed": local_changed,
                    "remote_changed": remote_changed,
                    "moved_or_renamed": moved_or_renamed,
                    "title_changed": title_changed,
                    "status_changed": status_changed,
                })
            else:
                in_sync_docs.append({"doc": doc, "remote": rch, "local_path": local_path})

        remote_deleted_docs: List[DocumentItem] = []
        local_new_docs: List[DocumentItem] = []

        for doc in self.manifest.documents:
            if book_id and doc.category != book_id:
                continue
            if id(doc) in matched_local_docs:
                continue
            was_synced = (doc.slug in state) or bool(
                doc.doc_id and any(isinstance(v, dict) and v.get("docId") == doc.doc_id for v in state.values())
            )
            if was_synced:
                remote_deleted_docs.append(doc)
            else:
                local_new_docs.append(doc)

        return {
            "remote_only_categories": remote_only_categories,
            "local_only_categories": local_only_categories,
            "remote_only_docs": remote_only_docs,
            "remote_deleted_docs": remote_deleted_docs,
            "local_new_docs": local_new_docs,
            "modified_docs": modified_docs,
            "in_sync_docs": in_sync_docs,
        }

    def sync_remote_categories_to_manifest(self, remote_cats: List[Dict[str, Any]]) -> List[CategoryItem]:
        """Adds any remote categories missing from local qwiki-project.json and updates changed titles/themes."""
        existing = {c.id: c for c in self.manifest.categories}
        added: List[CategoryItem] = []
        changed = False
        for rc in remote_cats:
            cid = (rc.get("id") or "").strip()
            if not cid:
                continue
            if cid not in existing:
                new_cat = CategoryItem(
                    id=cid,
                    title=rc.get("title") or cid.replace("-", " ").title(),
                    description=rc.get("description") or "",
                    parent=rc.get("parent") or None,
                    theme=rc.get("theme") or None,
                )
                self.manifest.categories.append(new_cat)
                existing[cid] = new_cat
                added.append(new_cat)
                changed = True
            else:
                cat = existing[cid]
                if rc.get("parent") and cat.parent != rc.get("parent"):
                    cat.parent = rc.get("parent")
                    changed = True
                if rc.get("description") and not cat.description:
                    cat.description = rc.get("description")
                    changed = True
                if rc.get("theme") and not cat.theme:
                    cat.theme = rc.get("theme")
                    changed = True

        if changed and self.manifest.project_root:
            manifest_path = self.manifest.project_root / "qwiki-project.json"
            if manifest_path.is_file():
                self.manifest.save(manifest_path)
        return added

    def pull_tree(
        self,
        book_id: Optional[str] = None,
        discover: bool = True,
        overwrite: bool = False,
        sync_meta: bool = True,
        prune_deleted: bool = False,
    ) -> Dict[str, Any]:
        """
        Full tree-level pull & reconciliation:
          1. Discovers remote categories (including nested subfolders) and syncs to qwiki-project.json.
          2. Pulls all existing local chapters (matching by immutable docId even if renamed/moved on live wiki).
          3. Discovers and downloads any brand-new chapters created on the live wiki (when discover=True).
          4. Detects chapters deleted on the live wiki (and optionally prunes them if prune_deleted=True).
        """
        status = self.compute_tree_status(book_id=book_id)
        tree = self.client.get_tree(book_id=book_id)
        added_cats: List[CategoryItem] = []
        if discover or sync_meta:
            added_cats = self.sync_remote_categories_to_manifest(tree.get("categories", []))

        pulled_results: List[Dict[str, Any]] = []
        # 1. Pull matched documents (both modified and any missing local files)
        for rch in tree.get("chapters", []):
            doc = self.match_local_document(rch)
            if doc is not None:
                res = self.pull_document(
                    slug=rch.get("slug") or doc.slug,
                    doc=doc,
                    overwrite=overwrite,
                    sync_meta=sync_meta,
                )
                pulled_results.append(res)
            elif discover:
                res = self.pull_document(
                    slug=rch.get("slug", ""),
                    doc=None,
                    overwrite=overwrite,
                    sync_meta=True,
                )
                pulled_results.append(res)

        pruned_docs: List[str] = []
        if prune_deleted and status["remote_deleted_docs"]:
            state = self.load_state()
            for rdel in status["remote_deleted_docs"]:
                local_p = self.resolve_local_doc_path(rdel, {"bookId": rdel.category, "slug": rdel.slug, "type": rdel.doc_type})
                if local_p.is_file():
                    local_p.unlink()
                if rdel in self.manifest.documents:
                    self.manifest.documents.remove(rdel)
                state.pop(rdel.slug, None)
                pruned_docs.append(rdel.slug)
            self.save_state(state)
            if self.manifest.project_root:
                manifest_path = self.manifest.project_root / "qwiki-project.json"
                if manifest_path.is_file():
                    self.manifest.save(manifest_path)

        return {
            "added_categories": added_cats,
            "pulled": pulled_results,
            "remote_only_docs": status["remote_only_docs"],
            "remote_deleted_docs": status["remote_deleted_docs"],
            "pruned_docs": pruned_docs,
            "local_new_docs": status["local_new_docs"],
        }
