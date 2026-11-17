"""
Publisher orchestration engine for Qwiki Builder.
Manages categories, asset resolution, document uploads, and in-place synchronization.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .assets import AssetManager
from .client import QwikiClient, QwikiClientError
from .links import LinkManager
from .manifest import DocumentItem, QwikiProjectManifest
from .sync import SyncManager, sha256_text


class QwikiPublisher:
    """High-level publisher synchronizing local documentation suites to Standalone Qwiki."""

    def __init__(self, manifest: QwikiProjectManifest, client: QwikiClient):
        self.manifest = manifest
        self.client = client
        self.docs_path = manifest.get_docs_path()
        self.assets_path = manifest.get_assets_path()
        self.project_root = manifest.project_root or Path.cwd()
        self.asset_manager = AssetManager(client, self.assets_path)
        self.link_manager = LinkManager(manifest)
        self.sync_manager = SyncManager(manifest, client)

    def sync_themes(self, dry_run: bool = False) -> Dict[str, str]:
        """
        Uploads any local custom theme CSS files referenced by site, categories, or documents,
        and applies the site-level theme if configured in the manifest.
        Returns a mapping of theme_ref -> remote_theme_filename.
        """
        refs: List[str] = []
        if self.manifest.theme:
            refs.append(self.manifest.theme)
        for cat in self.manifest.categories:
            if cat.theme:
                refs.append(cat.theme)
        for doc in self.manifest.documents:
            if doc.theme:
                refs.append(doc.theme)

        resolved_map: Dict[str, str] = {}
        uploaded_files: set[str] = set()

        for ref in refs:
            if ref in resolved_map:
                continue
            theme_name, local_path = self.manifest.resolve_theme_ref(ref)
            if not theme_name:
                continue
            resolved_map[ref] = theme_name
            if local_path is not None and theme_name not in uploaded_files:
                if dry_run:
                    print(f"🎨 [DRY-RUN] Would upload custom theme: {theme_name} ({local_path})")
                else:
                    css_content = local_path.read_text(encoding="utf-8")
                    self.client.save_theme(theme_name, css_content)
                    print(f"  🎨 Uploaded custom theme: {theme_name}")
                uploaded_files.add(theme_name)

        if self.manifest.theme:
            site_theme_name = resolved_map.get(self.manifest.theme, self.manifest.theme)
            if dry_run:
                print(f"🎨 [DRY-RUN] Would set site theme: {site_theme_name}")
            else:
                self.client.set_site_theme(site_theme_name)
                print(f"  🎨 Applied site theme: {site_theme_name}")

        return resolved_map

    def verify_and_create_categories(self, dry_run: bool = False) -> Dict[str, str]:
        """
        Verifies all manifest categories exist on remote Qwiki, creating any missing ones
        and syncing category-level theme metadata when specified.
        Returns a mapping of category_id -> title.
        """
        if dry_run:
            print("🔍 [DRY-RUN] Checking remote categories...")
            return {c.id: c.title for c in self.manifest.categories}

        remote_list = self.client.list_categories()
        existing_ids = {c.get("id"): c.get("title", "") for c in remote_list}
        existing_themes = {c.get("id"): c.get("theme", "") for c in remote_list}

        missing = [c for c in self.manifest.categories if c.id not in existing_ids]
        if missing:
            print(f"📁 Creating {len(missing)} missing remote category/categories...")
            for cat in missing:
                cat_theme, _ = self.manifest.resolve_theme_ref(cat.theme)
                res = self.client.create_category(
                    category_id=cat.id,
                    title=cat.title,
                    description=cat.description,
                    parent=cat.parent,
                    theme=cat_theme,
                )
                if res.get("success"):
                    print(f"  ✅ Created category: [{cat.id}] \"{cat.title}\"")
                    existing_ids[cat.id] = cat.title
                else:
                    raise RuntimeError(f"Failed to create category '{cat.id}': {res.get('error')}")

        for cat in self.manifest.categories:
            if cat.id in existing_ids and cat.theme:
                cat_theme, _ = self.manifest.resolve_theme_ref(cat.theme)
                if cat_theme and existing_themes.get(cat.id, "") != cat_theme:
                    self.client.update_category(category_id=cat.id, title=cat.title, theme=cat_theme)
                    print(f"  🎨 Applied category theme [{cat.id}]: {cat_theme}")

        return existing_ids

    def publish_document_item(
        self,
        doc: DocumentItem,
        update: bool = True,
        dry_run: bool = False,
        force: bool = False,
        expected_sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Publishes a single document item: reads file, uploads/rewrites assets, and posts to Qwiki.
        Applies optimistic concurrency checks via tracked .qwiki-sync SHA-256 unless force=True.
        """
        doc_file = (self.docs_path / doc.file).resolve()
        if not doc_file.is_file():
            cand_root = (self.project_root / doc.file).resolve()
            if cand_root.is_file():
                doc_file = cand_root
            else:
                raise FileNotFoundError(f"Document file not found: {doc.file}")

        content = doc_file.read_text(encoding="utf-8")

        # Process and upload referenced images
        if not dry_run:
            processed_content, _ = self.asset_manager.process_content_images(
                content=content,
                doc_dir=doc_file.parent,
                auto_upload=True,
            )
        else:
            processed_content = content

        # Process and resolve internal hyperlinks to include canonical '<category>/<slug>'
        processed_content, link_rewrites = self.link_manager.process_content_links(
            content=processed_content,
            doc_dir=doc_file.parent,
        )

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "title": doc.title,
                "slug": doc.slug,
                "category": doc.category,
                "url": f"{self.client.base_url}/{doc.category}/{doc.slug}",
            }

        effective_expected_sha = expected_sha256
        if not effective_expected_sha and not force:
            effective_expected_sha = self.sync_manager.get_expected_sha256(doc.slug)

        doc_theme, doc_theme_path = self.manifest.resolve_theme_ref(doc.theme)
        if doc_theme_path is not None:
            self.client.save_theme(doc_theme, doc_theme_path.read_text(encoding="utf-8"))

        try:
            res = self.client.publish_document(
                book_id=doc.category,
                title=doc.title,
                content=processed_content,
                slug=doc.slug,
                doc_type=doc.doc_type,
                status=doc.status,
                description=doc.description,
                share_key=doc.share_key,
                public_shareable=doc.public_shareable,
                update=update,
                overwrite=True,
                approver="QwikiBuilder",
                expected_sha256=effective_expected_sha,
                force=force,
                theme=doc_theme,
            )
        except QwikiClientError as e:
            if e.error_code in ("CONFLICT_SHA256_MISMATCH", "LOCKED_BY_OTHER"):
                raise QwikiClientError(
                    f"{e} — Run 'qwiki-builder diff {doc.slug}' and 'qwiki-builder pull {doc.slug}' "
                    f"to reconcile remote changes/feedback, or pass '--force' to override.",
                    status_code=e.status_code,
                    response_body=e.response_body,
                    error_code=e.error_code,
                    response_data=e.response_data,
                ) from e
            raise

        new_sha = res.get("sha256") or sha256_text(processed_content)
        self.sync_manager.record_synced_baseline(
            slug=res.get("slug") or doc.slug,
            book_id=res.get("bookId") or doc.category,
            doc_type=doc.doc_type,
            remote_sha256=new_sha,
            content=processed_content,
            meta={
                "docId": res.get("docId", ""),
                "shareKey": res.get("shareKey") or doc.share_key or "",
                "status": res.get("status") or doc.status,
                "title": doc.title,
                "dateModified": res.get("statusUpdatedAt", ""),
            },
        )
        return res

    def publish_all(
        self,
        dry_run: bool = False,
        upload_assets_first: bool = True,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Full synchronization: verifies categories, uploads assets, and publishes all documents.
        """
        start_time = time.time()
        print("=" * 80)
        mode_str = " [DRY-RUN]" if dry_run else ""
        print(f"🚀 SYNCHRONIZING DOCUMENTATION SUITE{mode_str}: \"{self.manifest.name}\"")
        print(f"🌐 Target Wiki: {self.client.base_url}")
        print(f"📚 Documents:   {len(self.manifest.documents)} registered chapters")
        print("=" * 80)

        # 1. Themes & Categories
        self.sync_themes(dry_run=dry_run)
        self.verify_and_create_categories(dry_run=dry_run)

        # 2. Pre-upload assets if requested
        if upload_assets_first and not dry_run and self.assets_path.is_dir():
            print("\n🖼️ Scanning and uploading asset directory...")
            uploaded = self.asset_manager.upload_all_in_assets_dir()
            print(f"  ✅ {len(uploaded)} asset(s) ready.")

        # 3. Publish documents
        print(f"\n📄 Publishing {len(self.manifest.documents)} documents...")
        success_count = 0
        failed_docs: List[Tuple[str, str]] = []
        results: List[Dict[str, Any]] = []

        for idx, doc in enumerate(self.manifest.documents, 1):
            tag = f"[{idx:>2}/{len(self.manifest.documents)}]"
            try:
                res = self.publish_document_item(doc, update=True, dry_run=dry_run, force=force)
                results.append(res)
                success_count += 1
                status_tag = "🔄 Updated" if res.get("updated") else "✨ Created"
                url = res.get("url", "")
                share_key = res.get("shareKey", "")
                key_info = f" (share: {share_key})" if share_key else ""
                print(f"  {tag} ✅ {status_tag}: [{doc.category}] {doc.slug} ➔ {url}{key_info}")
            except Exception as e:
                failed_docs.append((doc.slug, str(e)))
                print(f"  {tag} ❌ Failed: [{doc.category}] {doc.slug} ➔ {e}")

            if not dry_run:
                time.sleep(0.2)

        elapsed = time.time() - start_time
        print("\n" + "=" * 80)
        print(f"🎉 SYNC FINISHED in {elapsed:.1f}s: {success_count}/{len(self.manifest.documents)} documents succeeded.")
        if failed_docs:
            print(f"⚠️ {len(failed_docs)} document(s) failed:")
            for slug, err in failed_docs:
                print(f"   • {slug}: {err}")
        print("=" * 80)

        return {
            "success": len(failed_docs) == 0,
            "total": len(self.manifest.documents),
            "synced": success_count,
            "failed": failed_docs,
            "elapsed_seconds": elapsed,
            "results": results,
        }

    def clean_reload(self) -> Dict[str, Any]:
        """
        Completely resets remote chapters in project categories and cleanly reloads all documents.
        """
        print("=" * 80)
        print("🔄 CLEAN RELOAD INITIATED")
        print(f"Target categories: {[c.id for c in self.manifest.categories]}")
        print("=" * 80)

        # 1. Categories
        self.verify_and_create_categories(dry_run=False)

        # 2. Fetch existing chapters
        target_cat_ids = {c.id for c in self.manifest.categories}
        all_remote = self.client.list_chapters()
        to_purge = [ch for ch in all_remote if ch.get("bookId") in target_cat_ids]

        if to_purge:
            print(f"\nStep 1: Purging {len(to_purge)} existing/duplicate remote chapter(s)...")
            for ch in to_purge:
                slug = ch.get("slug")
                cat_id = ch.get("bookId")
                try:
                    self.client.delete_chapter(slug, cat_id)
                    print(f"  🗑️ Purged: [{cat_id}] {slug}")
                except Exception as e:
                    print(f"  ⚠️ Error purging {slug}: {e}")
        else:
            print("\nStep 1: No existing chapters to purge in target categories.")

        # 3. Publish canonical documents
        print("\nStep 2: Publishing canonical documents...")
        return self.publish_all(dry_run=False, upload_assets_first=True)
