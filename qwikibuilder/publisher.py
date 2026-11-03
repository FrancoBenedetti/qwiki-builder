"""
Publisher orchestration engine for Qwiki Builder.
Manages categories, asset resolution, document uploads, and in-place synchronization.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .assets import AssetManager
from .client import QwikiClient
from .manifest import DocumentItem, QwikiProjectManifest


class QwikiPublisher:
    """High-level publisher synchronizing local documentation suites to Standalone Qwiki."""

    def __init__(self, manifest: QwikiProjectManifest, client: QwikiClient):
        self.manifest = manifest
        self.client = client
        self.docs_path = manifest.get_docs_path()
        self.assets_path = manifest.get_assets_path()
        self.project_root = manifest.project_root or Path.cwd()
        self.asset_manager = AssetManager(client, self.assets_path)

    def verify_and_create_categories(self, dry_run: bool = False) -> Dict[str, str]:
        """
        Verifies all manifest categories exist on remote Qwiki, creating any missing ones.
        Returns a mapping of category_id -> title.
        """
        if dry_run:
            print("🔍 [DRY-RUN] Checking remote categories...")
            return {c.id: c.title for c in self.manifest.categories}

        remote_list = self.client.list_categories()
        existing_ids = {c.get("id"): c.get("title", "") for c in remote_list}

        missing = [c for c in self.manifest.categories if c.id not in existing_ids]
        if missing:
            print(f"📁 Creating {len(missing)} missing remote category/categories...")
            for cat in missing:
                res = self.client.create_category(
                    category_id=cat.id,
                    title=cat.title,
                    description=cat.description,
                    parent=cat.parent,
                )
                if res.get("success"):
                    print(f"  ✅ Created category: [{cat.id}] \"{cat.title}\"")
                    existing_ids[cat.id] = cat.title
                else:
                    raise RuntimeError(f"Failed to create category '{cat.id}': {res.get('error')}")

        return existing_ids

    def publish_document_item(
        self,
        doc: DocumentItem,
        update: bool = True,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Publishes a single document item: reads file, uploads/rewrites assets, and posts to Qwiki.
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

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "title": doc.title,
                "slug": doc.slug,
                "category": doc.category,
                "url": f"{self.client.base_url}/{doc.category}/{doc.slug}",
            }

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
        )
        return res

    def publish_all(
        self,
        dry_run: bool = False,
        upload_assets_first: bool = True,
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

        # 1. Categories
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
                res = self.publish_document_item(doc, update=True, dry_run=dry_run)
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
