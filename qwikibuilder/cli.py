"""
Command Line Interface for Qwiki Builder.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from .assets import AssetManager
from .client import QwikiClient, QwikiClientError
from .config import (
    delete_profile,
    get_global_config_path,
    list_profiles,
    resolve_credentials,
    set_profile,
)
from .dedup import QwikiDeduplicator
from .manifest import CategoryItem, DocumentItem, QwikiProjectManifest
from .publisher import QwikiPublisher
from .sync import SyncManager
from .validator import ProjectValidator

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _resolve_manifest(manifest_arg: Optional[str]) -> QwikiProjectManifest:
    """Finds and loads the target manifest file."""
    start_path = Path(manifest_arg) if manifest_arg else Path.cwd()
    if start_path.is_file():
        return QwikiProjectManifest.load(start_path)

    found = QwikiProjectManifest.find_manifest_file(start_path)
    if not found:
        print(f"❌ Error: No qwiki-project.json found in '{start_path}' or its parent directories.")
        print("Run 'qwiki-builder init' to scaffold a new project.")
        sys.exit(1)

    return QwikiProjectManifest.load(found)


def _get_client(manifest: QwikiProjectManifest, args: argparse.Namespace) -> QwikiClient:
    """Constructs an authenticated QwikiClient using resolved credentials."""
    try:
        url, key = resolve_credentials(
            explicit_url=getattr(args, "url", None),
            explicit_key=getattr(args, "key", None),
            profile_name=getattr(args, "profile", None),
            project_url=manifest.wiki_url,
            project_key=manifest.api_key,
            project_profile=manifest.profile,
        )
    except ValueError as e:
        print(f"❌ Configuration Error: {e}")
        sys.exit(1)

    return QwikiClient(base_url=url, api_key=key)


# ==============================================================================
# Commands
# ==============================================================================

def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold a new documentation project from a template."""
    dest = Path(args.path or ".").resolve()
    dest.mkdir(parents=True, exist_ok=True)

    template_type = args.template or "user-guide"
    source_template_dir = TEMPLATES_DIR / template_type

    if not source_template_dir.is_dir() and template_type != "blank":
        print(f"❌ Error: Unknown template '{template_type}'. Available templates:")
        for t in sorted(TEMPLATES_DIR.iterdir()):
            if t.is_dir():
                print(f"  • {t.name}")
        print("  • blank")
        return 1

    print(f"📁 Scaffolding new Qwiki documentation project in: {dest}")
    print(f"📋 Template preset: {template_type}")

    project_name = args.name or dest.name.replace("-", " ").title()

    if template_type != "blank" and source_template_dir.is_dir():
        # Copy template files
        for item in source_template_dir.iterdir():
            target_item = dest / item.name
            if item.is_dir():
                if target_item.exists():
                    shutil.copytree(item, target_item, dirs_exist_ok=True)
                else:
                    shutil.copytree(item, target_item)
            else:
                shutil.copy2(item, target_item)

        # Update project name and credentials if provided
        manifest_file = dest / "qwiki-project.json"
        if manifest_file.is_file():
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                data["name"] = project_name
                if args.url:
                    data["wiki_url"] = args.url
                if args.key:
                    data["api_key"] = args.key
                if args.profile:
                    data["profile"] = args.profile
                manifest_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  ⚠️ Warning updating qwiki-project.json: {e}")
    else:
        # Blank template
        docs_dir = dest / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = docs_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        intro_file = docs_dir / "01-overview.md"
        intro_file.write_text(f"# {project_name}\n\nWelcome to {project_name}.\n", encoding="utf-8")

        manifest = QwikiProjectManifest(
            name=project_name,
            slug=dest.name,
            version="1.0.0",
            doc_type_preset="custom",
            wiki_url=args.url,
            api_key=args.key,
            profile=args.profile,
            categories=[CategoryItem(id="general", title="General Documentation")],
            documents=[
                DocumentItem(
                    file="01-overview.md",
                    category="general",
                    slug="overview",
                    title=project_name,
                )
            ],
            project_root=dest,
        )
        manifest.save()

    # Ensure assets directory and subfolders exist for all presets
    assets_img_dir = dest / "docs" / "assets" / "images"
    assets_vid_dir = dest / "docs" / "assets" / "videos"
    assets_img_dir.mkdir(parents=True, exist_ok=True)
    assets_vid_dir.mkdir(parents=True, exist_ok=True)
    assets_readme = dest / "docs" / "assets" / "README.md"
    if not assets_readme.exists():
        assets_readme.write_text(
            "# Documentation Assets (Images, Screenshots & Videos)\n\n"
            "Store screenshots, diagrams, and video files here to enrich your documentation.\n\n"
            "### Supported Media Types:\n"
            "- **Images & Screenshots:** `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.gif`\n"
            "- **Video Screencasts & Demos:** `.mp4`, `.webm`, `.ogg`, `.ogv`, `.mov`\n\n"
            "### Usage in Markdown:\n"
            "- **Screenshot / Diagram:** `![UI Overview](assets/images/overview.png)`\n"
            "- **Video Player (Auto-Embedded):** `[Video Walkthrough](assets/videos/demo.mp4)` or `![Demo](assets/videos/demo.mp4)`\n"
            "- **External Video:** Place standalone YouTube, Vimeo, or Loom URLs on their own line.\n\n"
            "When running `qwiki-builder publish`, local asset references are automatically uploaded "
            "to Standalone Qwiki via the headless REST API and rewritten to remote URLs.\n",
            encoding="utf-8",
        )

    # Create root README if not present
    readme_path = dest / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            f"# {project_name}\n\n"
            f"Online documentation suite managed by [qwiki-builder](https://github.com/FrancoBenedetti/qwiki-builder).\n\n"
            "## Commands\n\n"
            "```bash\n"
            "# Validate documentation integrity\n"
            "qwiki-builder validate\n\n"
            "# Synchronize all documents to Qwiki\n"
            "qwiki-builder publish\n\n"
            "# Preview deployment without uploading\n"
            "qwiki-builder publish --dry-run\n"
            "```\n",
            encoding="utf-8",
        )

    print("✨ Project scaffolded successfully!")
    print(f"👉 Next steps:\n   cd {dest}\n   qwiki-builder validate\n   qwiki-builder publish --dry-run")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Manage global and named profiles in ~/.config/qwiki-builder/config.json."""
    if args.show_path:
        print(f"Global configuration file: {get_global_config_path()}")
        return 0

    if args.list:
        profiles = list_profiles()
        print("=" * 80)
        print(f"🔧 CONFIGURED QWIKI PROFILES ({get_global_config_path()})")
        print("=" * 80)
        if not profiles:
            print("  (No profiles configured yet. Add one with 'qwiki-builder config --profile <name> --url <url> --key <key>')")
        else:
            for name, details in profiles.items():
                print(f"  • Profile: [{name}]")
                print(f"    URL:     {details.get('url', 'N/A')}")
                key_preview = details.get("api_key", "")
                masked_key = f"{key_preview[:8]}...{key_preview[-4:]}" if len(key_preview) > 12 else "****"
                print(f"    API Key: {masked_key}")
        print("=" * 80)
        return 0

    if args.delete:
        prof_name = args.profile or "default"
        if delete_profile(prof_name):
            print(f"✅ Deleted profile '{prof_name}'.")
            return 0
        else:
            print(f"❌ Error: Profile '{prof_name}' not found.")
            return 1

    if args.url or args.key:
        prof_name = args.profile or "default"
        url = args.url or ""
        key = args.key or ""

        # If updating existing profile and one field omitted, preserve existing
        if not url or not key:
            existing = list_profiles().get(prof_name, {})
            url = url or existing.get("url", "")
            key = key or existing.get("api_key", "")

        if not url or not key:
            print("❌ Error: Both --url and --key are required to create/update a profile.")
            return 1

        set_profile(prof_name, url, key, set_default=args.set_default)
        print(f"✅ Profile '{prof_name}' saved successfully!")
        return 0

    # Display current profile
    prof_name = args.profile or "default"
    prof = list_profiles().get(prof_name)
    if prof:
        print(f"Profile [{prof_name}]:")
        print(f"  URL: {prof.get('url')}")
        key_preview = prof.get("api_key", "")
        masked_key = f"{key_preview[:8]}...{key_preview[-4:]}" if len(key_preview) > 12 else "****"
        print(f"  API Key: {masked_key}")
    else:
        print(f"Profile '{prof_name}' is not configured.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate documentation project files, structure, links, and assets."""
    manifest = _resolve_manifest(args.manifest)
    validator = ProjectValidator(manifest)
    report = validator.validate()

    print("=" * 80)
    print(f"📋 VALIDATION REPORT: \"{manifest.name}\" ({manifest.slug})")
    print(f"📁 Categories: {report.stats['categories']} | 📄 Documents: {report.stats['documents']} | 🖼️ Images: {report.stats['images']} | 📝 Words: {report.stats['word_count']}")
    print("=" * 80)

    if report.issues:
        for issue in report.issues:
            icon = "❌" if issue.level == "ERROR" else "⚠️"
            location = f" ({issue.file})" if issue.file else ""
            line_info = f":L{issue.line}" if issue.line else ""
            print(f"  {icon} [{issue.category}] {issue.message}{location}{line_info}")
    else:
        print("  ✅ All checks passed! No errors or warnings detected.")

    print("=" * 80)
    if report.errors:
        print(f"❌ FAILED: {len(report.errors)} error(s) found. Please resolve before publishing.")
        return 1
    elif report.warnings:
        print(f"⚠️ PASSED WITH WARNINGS: {len(report.warnings)} warning(s) found.")
        return 0
    else:
        print("🎉 PASSED: Project is ready for publishing!")
        return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Synchronize documentation suite to remote Qwiki."""
    manifest = _resolve_manifest(args.manifest)

    # Perform validation check first
    validator = ProjectValidator(manifest)
    report = validator.validate()
    if report.errors:
        print(f"❌ Cannot publish: {len(report.errors)} validation error(s) must be resolved first:")
        for err in report.errors:
            print(f"   • [{err.category}] {err.message} ({err.file})")
        return 1

    client = _get_client(manifest, args)
    publisher = QwikiPublisher(manifest, client)

    if args.reload:
        res = publisher.clean_reload()
    else:
        res = publisher.publish_all(
            dry_run=args.dry_run,
            upload_assets_first=not args.no_assets,
            force=getattr(args, "force", False),
        )

    return 0 if res.get("success") else 1


def _match_manifest_doc(manifest: QwikiProjectManifest, target: str) -> Optional[DocumentItem]:
    """Finds a DocumentItem matching slug, doc_id, shareKey, relative file path, filename, or stem."""
    clean = target.strip()
    for d in manifest.documents:
        stem = d.file[:-len(".form.json")] if d.file.lower().endswith(".form.json") else Path(d.file).stem
        if (
            clean in (d.slug, d.file, Path(d.file).name, stem)
            or (d.share_key and clean == d.share_key)
            or (d.doc_id and clean == d.doc_id)
        ):
            return d
    return None


def cmd_update(args: argparse.Namespace) -> int:
    """Update a specific document in place by file or slug."""
    manifest = _resolve_manifest(args.manifest)
    target = args.target.strip()

    matched_doc = _match_manifest_doc(manifest, target)
    if not matched_doc:
        print(f"❌ Error: Document '{target}' not found in manifest.")
        print("Available documents:")
        for d in manifest.documents:
            print(f"  • {d.file:<40} (slug: {d.slug})")
        return 1

    client = _get_client(manifest, args)
    publisher = QwikiPublisher(manifest, client)

    print(f"🔄 Updating document in place: [{matched_doc.category}] {matched_doc.slug} ({matched_doc.file})...")
    try:
        res = publisher.publish_document_item(
            matched_doc,
            update=True,
            dry_run=args.dry_run,
            force=getattr(args, "force", False),
            expected_sha256=getattr(args, "expected_sha256", None),
        )
        status_tag = "🔄 Updated in-place" if res.get("updated") else "✨ Created"
        print(f"✅ {status_tag} successfully!")
        print(f"   • Slug: {res.get('slug')}")
        print(f"   • URL:  {res.get('url')}")
        if res.get("shareKey"):
            print(f"   • Share Key: {res.get('shareKey')}")
        if res.get("sha256"):
            print(f"   • SHA-256:   {res.get('sha256')[:16]}...")
        return 0
    except Exception as e:
        print(f"❌ Update failed: {e}")
        return 1


def cmd_pull(args: argparse.Namespace) -> int:
    """Download published document(s), comments, and talk page from remote Qwiki before editing."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    sync = SyncManager(manifest, client)

    icon_map = {
        "created": "✨ Downloaded",
        "updated": "⬇️ Updated local",
        "merged": "🔀 Auto-merged",
        "up_to_date": "✅ Up to date",
        "conflict": "⚠️ Conflict",
    }

    has_conflicts_or_errors = False
    discover = not getattr(args, "no_discover", False)
    prune_deleted = getattr(args, "prune_deleted", False)

    if args.all or not args.target:
        if discover:
            try:
                tree_res = sync.pull_tree(
                    book_id=getattr(args, "book_id", None),
                    discover=True,
                    overwrite=args.overwrite,
                    sync_meta=True if args.sync_meta or discover else False,
                    prune_deleted=prune_deleted,
                )
                if tree_res["added_categories"]:
                    print(f"📁 Discovered {len(tree_res['added_categories'])} new remote category/categories:")
                    for cat in tree_res["added_categories"]:
                        print(f"   • [{cat.id}] \"{cat.title}\"")
                for res in tree_res["pulled"]:
                    outcome = res["outcome"]
                    print(f"{icon_map.get(outcome, outcome)}: [{res['bookId']}] {res['slug']} ➔ {res['local_path']}")
                    print(
                        f"   • Comments: {res['comments_count']} | Talk topics: {res['talk_topics_count']} | "
                        f"Feedback digest: {res['feedback_md']}"
                    )
                    lock = res.get("lock") or {}
                    if lock.get("locked"):
                        print(
                            f"   ⚠️ ACTIVE UI LOCK: Currently being edited by '{lock.get('user', 'Unknown')}' "
                            f"(expires in {lock.get('expiresIn', 0)}s)"
                        )
                    if outcome == "conflict":
                        has_conflicts_or_errors = True
                        print(
                            f"   ⚠️ Local edits and remote changes diverged! Remote copy saved to: {res['conflict_path']}\n"
                            f"      Merge manually into {res['local_path']}, then run 'qwiki-builder update {res['slug']} --force' "
                            f"(or re-pull with '--overwrite')."
                        )
                if tree_res["remote_deleted_docs"] and not prune_deleted:
                    print(f"\n⚠️ {len(tree_res['remote_deleted_docs'])} local document(s) were deleted on the remote wiki:")
                    for rdel in tree_res["remote_deleted_docs"]:
                        print(f"   • [{rdel.category}] {rdel.slug} ({rdel.file})")
                    print("   Run 'qwiki-builder pull --all --prune-deleted' to remove them locally, or 'qwiki-builder publish' to re-create them.")
                elif tree_res["pruned_docs"]:
                    print(f"\n🗑️ Pruned {len(tree_res['pruned_docs'])} remote-deleted document(s): {', '.join(tree_res['pruned_docs'])}")
                return 1 if has_conflicts_or_errors else 0
            except Exception as e:
                print(f"❌ Tree pull failed: {e}")
                return 1

        if not manifest.documents:
            print("ℹ️ No documents registered in manifest.")
            return 0
        targets = [(d.slug, d) for d in manifest.documents]
    else:
        matched = _match_manifest_doc(manifest, args.target)
        slug_val = matched.slug if matched else args.target.strip()
        targets = [(slug_val, matched)]

    for slug_val, doc in targets:
        try:
            res = sync.pull_document(
                slug=slug_val,
                doc=doc,
                overwrite=args.overwrite,
                sync_meta=args.sync_meta,
            )
            outcome = res["outcome"]
            print(f"{icon_map.get(outcome, outcome)}: [{res['bookId']}] {res['slug']} ➔ {res['local_path']}")
            print(
                f"   • Comments: {res['comments_count']} | Talk topics: {res['talk_topics_count']} | "
                f"Feedback digest: {res['feedback_md']}"
            )
            lock = res.get("lock") or {}
            if lock.get("locked"):
                print(
                    f"   ⚠️ ACTIVE UI LOCK: Currently being edited by '{lock.get('user', 'Unknown')}' "
                    f"(expires in {lock.get('expiresIn', 0)}s)"
                )
            if res.get("fallback_llm_api"):
                print("   ℹ️ Pulled via legacy api/llm.php fallback (upgrade Standalone Qwiki for raw HTML/draft support).")
            if outcome == "conflict":
                has_conflicts_or_errors = True
                print(
                    f"   ⚠️ Local edits and remote changes diverged! Remote copy saved to: {res['conflict_path']}\n"
                    f"      Merge manually into {res['local_path']}, then run 'qwiki-builder update {res['slug']} --force' "
                    f"(or re-pull with '--overwrite')."
                )
        except Exception as e:
            has_conflicts_or_errors = True
            print(f"❌ Failed to pull '{slug_val}': {e}")

    return 1 if has_conflicts_or_errors else 0


def cmd_status(args: argparse.Namespace) -> int:
    """Compare live remote wiki tree against local manifest and .qwiki-sync baselines."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    sync = SyncManager(manifest, client)

    try:
        st = sync.compute_tree_status(book_id=getattr(args, "book_id", None))
    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return 1

    print("=" * 80)
    print(f"📊 SYNC STATUS: \"{manifest.name}\" <-> {client.base_url}")
    print("=" * 80)

    if st["remote_only_categories"]:
        print(f"\n📁 New Remote Categories ({len(st['remote_only_categories'])}):")
        for rc in st["remote_only_categories"]:
            print(f"   + [{rc.get('id')}] \"{rc.get('title')}\"")

    if st["local_only_categories"]:
        print(f"\n📁 Local-Only Categories ({len(st['local_only_categories'])}):")
        for lc in st["local_only_categories"]:
            print(f"   • [{lc.id}] \"{lc.title}\" (will be created on publish)")

    if st["remote_only_docs"]:
        print(f"\n✨ New Remote Pages Not in Local Manifest ({len(st['remote_only_docs'])}):")
        for rch in st["remote_only_docs"]:
            print(f"   + [{rch.get('bookId')}] {rch.get('slug')} (\"{rch.get('title')}\", type: {rch.get('type')})")

    if st["local_new_docs"]:
        print(f"\n📝 New Local Pages Not Yet Published ({len(st['local_new_docs'])}):")
        for doc in st["local_new_docs"]:
            print(f"   + [{doc.category}] {doc.slug} ({doc.file})")

    if st["modified_docs"]:
        print(f"\n🔄 Modified / Diverged Pages ({len(st['modified_docs'])}):")
        for item in st["modified_docs"]:
            doc = item["doc"]
            rch = item["remote"]
            reasons = []
            if not item["local_exists"]:
                reasons.append("local file missing")
            elif item["local_changed"] and item["remote_changed"]:
                reasons.append("both local & remote edited")
            elif item["remote_changed"]:
                reasons.append("remote edited")
            elif item["local_changed"]:
                reasons.append("local edited")
            elif item["local_sha256"] != item["remote_sha256"]:
                reasons.append("content differs")
            if item["moved_or_renamed"]:
                reasons.append(f"moved/renamed on remote -> [{rch.get('bookId')}] {rch.get('slug')}")
            if item["title_changed"]:
                reasons.append(f"title: {doc.title!r} -> {rch.get('title')!r}")
            if item["status_changed"]:
                reasons.append(f"status: {doc.status} -> {rch.get('status')}")
            print(f"   ~ [{doc.category}] {doc.slug} ({', '.join(reasons)})")

    if st["remote_deleted_docs"]:
        print(f"\n🗑️ Deleted on Remote Wiki ({len(st['remote_deleted_docs'])}):")
        for doc in st["remote_deleted_docs"]:
            print(f"   - [{doc.category}] {doc.slug} ({doc.file})")

    print(f"\n✅ In Sync: {len(st['in_sync_docs'])} document(s)")
    print("=" * 80)
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Bidirectional synchronization: pull remote tree/changes/feedback, validate, and publish local changes."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    sync = SyncManager(manifest, client)

    print("=" * 80)
    print(f"🔄 BIDIRECTIONAL SYNC: \"{manifest.name}\" <-> {client.base_url}")
    print("=" * 80)

    try:
        pull_res = sync.pull_tree(
            book_id=getattr(args, "book_id", None),
            discover=not getattr(args, "no_discover", False),
            overwrite=False,
            sync_meta=True,
            prune_deleted=getattr(args, "prune_deleted", False),
        )
    except Exception as e:
        print(f"❌ Pull phase failed: {e}")
        return 1

    conflicts = [r for r in pull_res["pulled"] if r["outcome"] == "conflict"]
    for res in pull_res["pulled"]:
        if res["outcome"] != "up_to_date":
            print(f"  ⬇️ Pulled [{res['bookId']}] {res['slug']} ({res['outcome']})")

    if conflicts:
        print(f"\n❌ Stopping before publish: {len(conflicts)} merge conflict(s) require resolution:")
        for c in conflicts:
            print(f"   • [{c['bookId']}] {c['slug']}: remote saved to {c['conflict_path']}")
        return 1

    validator = ProjectValidator(manifest)
    report = validator.validate()
    if report.errors:
        print(f"\n❌ Cannot publish: {len(report.errors)} validation error(s) detected:")
        for err in report.errors:
            print(f"   • [{err.category}] {err.message} ({err.file})")
        return 1

    publisher = QwikiPublisher(manifest, client)
    pub_res = publisher.publish_all(
        dry_run=getattr(args, "dry_run", False),
        upload_assets_first=not getattr(args, "no_assets", False),
        force=getattr(args, "force", False),
    )
    return 0 if pub_res.get("success") else 1


def cmd_diff(args: argparse.Namespace) -> int:
    """Show differences, metadata drift, active lock, and comment/talk counts vs remote Qwiki."""
    manifest = _resolve_manifest(args.manifest)
    matched = _match_manifest_doc(manifest, args.target)
    slug_val = matched.slug if matched else args.target.strip()

    client = _get_client(manifest, args)
    sync = SyncManager(manifest, client)

    try:
        res = sync.diff_document(slug=slug_val, doc=matched)
    except Exception as e:
        print(f"❌ Diff failed for '{slug_val}': {e}")
        return 1

    rdoc = res["remote_doc"]
    print("=" * 80)
    print(f"🔍 DIFF REPORT: [{rdoc.get('bookId', '')}] {rdoc.get('slug', slug_val)}")
    print(f"   • Local file:  {res['local_path']} ({'exists' if res['local_exists'] else 'missing'})")
    print(f"   • Remote SHA:  {res['remote_sha256'][:16]}... | Tracked SHA: {(res['tracked_sha256'] or 'none')[:16]}")
    print(f"   • Discussions: {res['comments_count']} comment(s), {res['talk_topics_count']} Talk topic(s)")
    lock = res.get("lock") or {}
    if lock.get("locked"):
        print(f"   • Editor Lock: ⚠️ LOCKED by {lock.get('user', 'Unknown')} ({lock.get('expiresIn', 0)}s remaining)")
    else:
        print("   • Editor Lock: Unlocked")

    if res["meta_diffs"]:
        print("   • Metadata differences (local vs remote):")
        for field_name, loc_val, rem_val in res["meta_diffs"]:
            print(f"     - {field_name}: local={loc_val!r} vs remote={rem_val!r}")

    print("=" * 80)
    if res["diff_text"]:
        print(res["diff_text"], end="" if res["diff_text"].endswith("\n") else "\n")
    else:
        print("✅ Local content matches remote content identically.")
    return 0


def cmd_upload_assets(args: argparse.Namespace) -> int:
    """Pre-upload all images and media assets from assets_dir to remote Qwiki."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    assets_dir = manifest.get_assets_path()

    if not assets_dir.is_dir():
        print(f"ℹ️ Assets directory does not exist: {assets_dir}")
        return 0

    print("=" * 80)
    print(f"🖼️ UPLOADING ASSETS FROM: {assets_dir}")
    print(f"🌐 Target Wiki: {client.base_url}")
    print("=" * 80)

    mgr = AssetManager(client, assets_dir)
    uploaded = mgr.upload_all_in_assets_dir()

    print(f"\n✅ Uploaded {len(uploaded)} asset(s):")
    for name, url in uploaded.items():
        print(f"  • {name:<30} ➔ {url}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List remote chapters on Qwiki and identify duplicates or missing files."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    deduper = QwikiDeduplicator(client, manifest)

    analysis = deduper.analyze(book_id=args.book_id)
    chapters = client.list_chapters(book_id=args.book_id)

    print("=" * 80)
    print(f"📚 REMOTE CHAPTERS ON {client.base_url} ({len(chapters)} total)")
    print("=" * 80)

    by_category: dict = {}
    for ch in chapters:
        by_category.setdefault(ch.get("bookId", "unknown"), []).append(ch)

    for cat_id, cat_chapters in sorted(by_category.items()):
        print(f"\n📂 Category [{cat_id}] ({len(cat_chapters)} documents):")
        for ch in cat_chapters:
            slug = ch.get("slug", "")
            title = ch.get("title", "")
            share_key = ch.get("shareKey", "")
            key_str = f" (key: {share_key})" if share_key else ""
            print(f"   • [{slug}] \"{title}\"{key_str}")

    print("\n" + "=" * 80)
    if analysis["duplicate_count"] > 0:
        print(f"⚠️ {analysis['duplicate_count']} potential duplicate(s) identified:")
        for dup in analysis["duplicates"]:
            print(f"   • [{dup['bookId']}] {dup['slug']} ➔ {dup['reason']}")
        print("Run 'qwiki-builder dedup' to remove duplicate chapters automatically.")
    else:
        print("✅ No duplicate chapters found on remote wiki.")
    print("=" * 80)
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    """Remove duplicate chapters and numerical slug suffixes from remote Qwiki."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    deduper = QwikiDeduplicator(client, manifest)

    print("=" * 80)
    mode_str = " [DRY-RUN]" if args.dry_run else ""
    print(f"🧹 DEDUPLICATING REMOTE CHAPTERS{mode_str} on {client.base_url}")
    print("=" * 80)

    deleted, failed = deduper.remove_duplicates(dry_run=args.dry_run, book_id=args.book_id)

    print("\n" + "=" * 80)
    print(f"✅ Deduplication finished: {deleted} removed, {failed} failed.")
    print("=" * 80)
    return 0 if failed == 0 else 1


def cmd_reload(args: argparse.Namespace) -> int:
    """Completely resets remote chapters in project categories and cleanly reloads all canonical files."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    publisher = QwikiPublisher(manifest, client)
    res = publisher.clean_reload()
    return 0 if res.get("success") else 1


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete a single chapter from the remote wiki by slug."""
    manifest = _resolve_manifest(args.manifest)
    client = _get_client(manifest, args)
    slug = args.slug.strip()

    print(f"🗑️ Deleting chapter '{slug}' from {client.base_url}...")
    try:
        res = client.delete_chapter(slug, book_id=args.book_id)
        if res.get("success"):
            print("✅ Chapter deleted successfully.")
            return 0
        else:
            print(f"❌ Failed to delete chapter: {res.get('error')}")
            return 1
    except Exception as e:
        print(f"❌ Error deleting chapter: {e}")
        return 1


def _get_client_optional_manifest(args: argparse.Namespace) -> tuple[Optional[QwikiProjectManifest], QwikiClient]:
    """Resolves a QwikiClient, loading qwiki-project.json if available or falling back to global/env credentials."""
    manifest_arg = getattr(args, "manifest", None)
    manifest: Optional[QwikiProjectManifest] = None
    if manifest_arg:
        manifest = _resolve_manifest(manifest_arg)
    else:
        found = QwikiProjectManifest.find_manifest_file(Path.cwd())
        if found:
            manifest = QwikiProjectManifest.load(found)

    client = _get_client(manifest or QwikiProjectManifest(), args)
    return manifest, client


def cmd_theme(args: argparse.Namespace) -> int:
    """Manage and apply theme CSS stylesheets at site, category, or page level."""
    import re

    manifest, client = _get_client_optional_manifest(args)
    action = args.theme_action

    try:
        if action == "list":
            res = client.list_themes()
            site_theme = res.get("siteTheme", "theme-default.css")
            themes = res.get("themes", [])
            print(f"🎨 Active site theme: {site_theme}")
            print(f"📋 Available themes ({len(themes)}):")
            for t in themes:
                marker = " (active site default)" if t == site_theme else ""
                print(f"   • {t}{marker}")
            return 0

        if action == "get":
            res = client.get_theme(args.theme)
            css = res.get("content", "")
            if args.out:
                out_path = Path(args.out).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(css, encoding="utf-8")
                print(f"✅ Saved '{args.theme}' to {out_path}")
            else:
                print(css)
            return 0

        if action == "upload":
            css_path = Path(args.file).resolve()
            if not css_path.is_file():
                print(f"❌ Error: CSS file not found: {css_path}")
                return 1
            theme_name = args.name.strip() if args.name else css_path.name
            if not re.match(r"^theme-[a-zA-Z0-9-]+\.css$", theme_name):
                print(f"❌ Error: Theme filename '{theme_name}' must match 'theme-<name>.css'.")
                return 1
            res = client.save_theme(theme_name, css_path.read_text(encoding="utf-8"))
            print(f"✅ Uploaded theme '{theme_name}' -> {res.get('url', '')}")
            return 0

        if action == "apply":
            theme_ref = args.theme.strip()
            local_css = Path(theme_ref).resolve()
            if local_css.is_file():
                theme_name = local_css.name
                if not re.match(r"^theme-[a-zA-Z0-9-]+\.css$", theme_name):
                    print(f"❌ Error: Theme filename '{theme_name}' must match 'theme-<name>.css'.")
                    return 1
                client.save_theme(theme_name, local_css.read_text(encoding="utf-8"))
                print(f"🎨 Uploaded custom theme: {theme_name}")
            else:
                theme_name = theme_ref
                if not re.match(r"^theme-[a-zA-Z0-9-]+\.css$", theme_name):
                    print(f"❌ Error: Theme name '{theme_name}' must match 'theme-<name>.css'.")
                    return 1

            if not (args.site or args.category or args.slug):
                print("❌ Error: Specify one target scope: --site, --category <id>, or --slug <slug>.")
                return 1

            if args.site:
                client.set_site_theme(theme_name)
                print(f"✅ Applied site-wide theme: {theme_name}")

            if args.category:
                client.update_category(category_id=args.category, theme=theme_name)
                print(f"✅ Applied category theme to [{args.category}]: {theme_name}")

            if args.slug:
                remote_doc = client.get_document(slug=args.slug, include_comments=False, include_talk=False)
                client.publish_document(
                    book_id=remote_doc["bookId"],
                    title=remote_doc["title"],
                    content=remote_doc["content"],
                    slug=remote_doc["slug"],
                    doc_type=remote_doc.get("type", "markdown"),
                    status=remote_doc.get("status", "published"),
                    description=remote_doc.get("description", ""),
                    share_key=remote_doc.get("shareKey") or None,
                    public_shareable=bool(remote_doc.get("publicShareable", True)),
                    update=True,
                    overwrite=True,
                    expected_sha256=remote_doc.get("sha256"),
                    theme=theme_name,
                )
                print(f"✅ Applied page theme to '{args.slug}': {theme_name}")
            return 0

        print(f"❌ Unknown theme action: {action}")
        return 1
    except Exception as e:
        print(f"❌ Theme command failed: {e}")
        return 1


def _format_submissions_table(schema: dict, submissions: list) -> str:
    """Formats form submission records as a readable Markdown table."""
    if not submissions:
        return "*No form responses recorded.*"

    fields = schema.get("fields", []) if isinstance(schema, dict) else []
    field_cols = [(f.get("id", ""), f.get("label") or f.get("id", "")) for f in fields if isinstance(f, dict) and f.get("id")]
    if not field_cols:
        # Infer keys from first submission data
        sample_data = submissions[0].get("data", {}) if isinstance(submissions[0], dict) else {}
        field_cols = [(k, k) for k in sample_data.keys()]

    headers = ["ID", "Date", "User"] + [lbl for _, lbl in field_cols]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for sub in submissions:
        data = sub.get("data", {}) if isinstance(sub, dict) else {}
        row = [
            str(sub.get("id", "")),
            str(sub.get("created_at", "")),
            str(sub.get("submitted_by", "guest")),
        ]
        for fid, _ in field_cols:
            val = data.get(fid, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            cell = str(val).replace("\n", " ").replace("|", "\\|")
            row.append(cell)
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def cmd_forms(args: argparse.Namespace) -> int:
    """Automate JSON web form creation/updates and monitor/export form responses."""
    import time

    manifest, client = _get_client_optional_manifest(args)
    action = args.forms_action

    try:
        if action == "list":
            forms = client.list_forms(book_id=getattr(args, "book_id", None))
            print("=" * 80)
            print(f"📋 JSON WEB FORMS ON {client.base_url} ({len(forms)} total)")
            print("=" * 80)
            if not forms:
                print("  (No forms registered on remote wiki)")
            else:
                for fm in forms:
                    latest = fm.get("latestSubmissionAt") or "never"
                    print(
                        f"  • [{fm.get('bookId')}] {fm.get('slug')} — \"{fm.get('title')}\"\n"
                        f"    Fields: {fm.get('fieldsCount', 0)} | Responses: {fm.get('submissionsCount', 0)} "
                        f"(latest: {latest}) | URL: {fm.get('url', '')}"
                    )
            print("=" * 80)
            return 0

        if action == "push":
            file_path = Path(args.file).resolve()
            if not file_path.is_file():
                print(f"❌ Error: Form schema file not found: {file_path}")
                return 1
            raw_content = file_path.read_text(encoding="utf-8")
            try:
                schema = json.loads(raw_content)
            except Exception as e:
                print(f"❌ Error: Invalid JSON in {file_path}: {e}")
                return 1
            if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list) or not schema["fields"]:
                print("❌ Error: Form schema must be a JSON object with a non-empty 'fields' array.")
                return 1

            matched_doc = _match_manifest_doc(manifest, args.file) if manifest else None
            cat_id = args.category or (matched_doc.category if matched_doc else None)
            if not cat_id:
                print("❌ Error: Specify --category <bookId> (or declare the form in qwiki-project.json).")
                return 1
            raw_stem = file_path.name[:-len(".form.json")] if file_path.name.lower().endswith(".form.json") else file_path.stem
            slug = args.slug or (matched_doc.slug if matched_doc else raw_stem)
            title = args.title or schema.get("title") or (matched_doc.title if matched_doc else slug.replace("-", " ").title())
            desc = schema.get("description") or (matched_doc.description if matched_doc else "")

            res = client.publish_document(
                book_id=cat_id,
                title=title,
                content=raw_content,
                slug=slug,
                doc_type="form",
                description=desc,
                doc_id=matched_doc.doc_id if matched_doc else None,
                share_key=matched_doc.share_key if matched_doc else None,
                update=True,
                overwrite=True,
                force=getattr(args, "force", False),
            )
            status_tag = "🔄 Updated form" if res.get("updated") else "✨ Created form"
            print(f"✅ {status_tag}: [{res.get('bookId')}] {res.get('slug')} ➔ {res.get('url')}")
            return 0

        if action == "responses":
            target = args.target.strip()
            matched_doc = _match_manifest_doc(manifest, target) if manifest else None
            slug = matched_doc.slug if matched_doc else target
            fmt = args.format.lower()
            api_fmt = "csv" if fmt == "csv" else "json"

            res = client.get_form_submissions(
                slug=slug,
                doc_id=matched_doc.doc_id if matched_doc else None,
                since=args.since,
                since_id=args.since_id,
                limit=args.limit,
                output_format=api_fmt,
            )

            if fmt == "csv":
                out_text = res.get("csv", "")
            elif fmt == "json":
                out_text = json.dumps(res.get("submissions", []), indent=2, ensure_ascii=False)
            else:
                out_text = _format_submissions_table(res.get("schema", {}), res.get("submissions", []))

            if args.out:
                out_path = Path(args.out).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(out_text, encoding="utf-8")
                print(f"✅ Exported {res.get('returned', 0)} response(s) for '{slug}' to {out_path}")
            else:
                print(out_text)
            return 0

        if action == "watch":
            target = args.target.strip()
            matched_doc = _match_manifest_doc(manifest, target) if manifest else None
            slug = matched_doc.slug if matched_doc else target
            interval = max(2, int(args.interval))
            max_polls = int(args.max_polls) if getattr(args, "max_polls", None) else 0

            last_seen_id: Optional[str] = args.since_id
            if not last_seen_id:
                init_res = client.get_form_submissions(slug=slug, doc_id=matched_doc.doc_id if matched_doc else None)
                subs = init_res.get("submissions", [])
                if subs:
                    # submissions are returned newest-first
                    last_seen_id = subs[0].get("id")
                print(f"👀 Watching form '{slug}' on {client.base_url} (total existing: {init_res.get('total', 0)}, interval: {interval}s)...")

            polls = 0
            try:
                while True:
                    polls += 1
                    res = client.get_form_submissions(
                        slug=slug,
                        doc_id=matched_doc.doc_id if matched_doc else None,
                        since_id=last_seen_id,
                    )
                    new_subs = list(reversed(res.get("submissions", [])))
                    for sub in new_subs:
                        last_seen_id = sub.get("id") or last_seen_id
                        print(f"\n🔔 New response [{sub.get('id')}] at {sub.get('created_at')} by {sub.get('submitted_by', 'guest')}:")
                        for k, v in (sub.get("data") or {}).items():
                            print(f"   • {k}: {v}")
                    if max_polls > 0 and polls >= max_polls:
                        break
                    time.sleep(interval)
            except KeyboardInterrupt:
                print("\n⏹️ Stopped watching form responses.")
            return 0

        if action == "delete-response":
            target = args.target.strip()
            matched_doc = _match_manifest_doc(manifest, target) if manifest else None
            slug = matched_doc.slug if matched_doc else target
            res = client.delete_form_submission(
                submission_id=args.id.strip(),
                slug=slug,
                doc_id=matched_doc.doc_id if matched_doc else None,
            )
            print(f"✅ Deleted submission '{args.id}' from '{slug}' ({res.get('remaining', 0)} remaining).")
            return 0

        if action == "clear-responses":
            target = args.target.strip()
            matched_doc = _match_manifest_doc(manifest, target) if manifest else None
            slug = matched_doc.slug if matched_doc else target
            client.clear_form_submissions(
                slug=slug,
                doc_id=matched_doc.doc_id if matched_doc else None,
            )
            print(f"✅ Cleared all submissions for form '{slug}'.")
            return 0

        print(f"❌ Unknown forms action: {action}")
        return 1
    except Exception as e:
        print(f"❌ Forms command failed: {e}")
        return 1


# ==============================================================================
# Argument Parsing Entry Point
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qwiki-builder",
        description="Generalised CLI & AI engine for automated creation and remote deployment of online manuals to Standalone Qwiki.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Scaffold a new Equipment Manual project
  qwiki-builder init my-manual --template equipment-manual

  # Configure global target wiki credentials
  qwiki-builder config --url https://wiki.example.com/docs --key your_api_key

  # Validate markdown files, links, and images
  qwiki-builder validate

  # Synchronize documents to remote Qwiki (dry-run preview)
  qwiki-builder publish --dry-run

  # Synchronize documents live
  qwiki-builder publish

  # Cleanly reload canonical documents and purge duplicates
  qwiki-builder reload
""",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 1.0.0")

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # init
    p_init = subparsers.add_parser("init", help="Scaffold a new documentation project from a template")
    p_init.add_argument("path", nargs="?", default=".", help="Target directory for project scaffolding")
    p_init.add_argument("-t", "--template", choices=["user-guide", "equipment-manual", "quality-manual", "safety-handbook", "sop", "blank"], default="user-guide", help="Template preset")
    p_init.add_argument("-n", "--name", help="Display title of the documentation suite")
    p_init.add_argument("--url", help="Remote Qwiki URL")
    p_init.add_argument("--key", help="Remote Qwiki API Key")
    p_init.add_argument("-p", "--profile", help="Named configuration profile")
    p_init.set_defaults(func=cmd_init)

    # config
    p_cfg = subparsers.add_parser("config", help="Manage global Qwiki connection profiles")
    p_cfg.add_argument("-l", "--list", action="store_true", help="List all configured profiles")
    p_cfg.add_argument("-p", "--profile", default="default", help="Profile name to view or update")
    p_cfg.add_argument("--url", help="Remote Qwiki URL")
    p_cfg.add_argument("--key", help="Remote Qwiki API Key")
    p_cfg.add_argument("--set-default", action="store_true", help="Set this profile as default")
    p_cfg.add_argument("--delete", action="store_true", help="Delete the specified profile")
    p_cfg.add_argument("--show-path", action="store_true", help="Show path to config.json")
    p_cfg.set_defaults(func=cmd_config)

    # validate
    p_val = subparsers.add_parser("validate", help="Validate project structure, manifest, links, and assets")
    p_val.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_val.set_defaults(func=cmd_validate)

    # publish
    p_pub = subparsers.add_parser("publish", help="Publish documentation suite to remote Qwiki")
    p_pub.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_pub.add_argument("-p", "--profile", help="Target named profile")
    p_pub.add_argument("--url", help="Override remote Qwiki URL")
    p_pub.add_argument("--key", help="Override remote API key")
    p_pub.add_argument("--dry-run", action="store_true", help="Preview publish actions without network modifications")
    p_pub.add_argument("--no-assets", action="store_true", help="Skip pre-uploading assets")
    p_pub.add_argument("--reload", action="store_true", help="Perform clean purge and reload of canonical docs")
    p_pub.add_argument("--force", action="store_true", help="Bypass optimistic SHA-256 and active UI lock guards")
    p_pub.set_defaults(func=cmd_publish)

    # update
    p_upd = subparsers.add_parser("update", help="Update a specific chapter in place on remote Qwiki")
    p_upd.add_argument("target", help="Relative file path or slug of the document to update")
    p_upd.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_upd.add_argument("-p", "--profile", help="Target named profile")
    p_upd.add_argument("--url", help="Override remote Qwiki URL")
    p_upd.add_argument("--key", help="Override remote API key")
    p_upd.add_argument("--dry-run", action="store_true", help="Preview update without network modifications")
    p_upd.add_argument("--force", action="store_true", help="Bypass optimistic SHA-256 and active UI lock guards")
    p_upd.add_argument("--expected-sha256", help="Explicit remote SHA-256 baseline to enforce before overwriting")
    p_upd.set_defaults(func=cmd_update)

    # pull
    p_pul = subparsers.add_parser("pull", help="Download live document(s), comments, and talk pages before editing")
    p_pul.add_argument("target", nargs="?", help="Relative file path, slug, or shareKey (omit or use --all for full suite)")
    p_pul.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_pul.add_argument("-p", "--profile", help="Target named profile")
    p_pul.add_argument("--url", help="Override remote Qwiki URL")
    p_pul.add_argument("--key", help="Override remote API key")
    p_pul.add_argument("--book-id", help="Filter tree pull by category ID")
    p_pul.add_argument("--all", action="store_true", help="Pull all documents and discover new remote categories/pages")
    p_pul.add_argument("--no-discover", action="store_true", help="Only pull chapters already declared in local qwiki-project.json")
    p_pul.add_argument("--prune-deleted", action="store_true", help="Remove local files and manifest entries for chapters deleted on remote wiki")
    p_pul.add_argument("--overwrite", action="store_true", help="Overwrite local edits with remote content")
    p_pul.add_argument("--sync-meta", action="store_true", help="Sync title, status, and description from remote into qwiki-project.json")
    p_pul.set_defaults(func=cmd_pull)

    # status
    p_sts = subparsers.add_parser("status", help="Compare live remote wiki tree against local manifest and baselines")
    p_sts.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_sts.add_argument("-p", "--profile", help="Target named profile")
    p_sts.add_argument("--url", help="Override remote Qwiki URL")
    p_sts.add_argument("--key", help="Override remote API key")
    p_sts.add_argument("--book-id", help="Filter status check by category ID")
    p_sts.set_defaults(func=cmd_status)

    # sync
    p_syn = subparsers.add_parser("sync", help="Bidirectional sync: pull remote tree/changes/feedback, validate, and publish local changes")
    p_syn.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_syn.add_argument("-p", "--profile", help="Target named profile")
    p_syn.add_argument("--url", help="Override remote Qwiki URL")
    p_syn.add_argument("--key", help="Override remote API key")
    p_syn.add_argument("--book-id", help="Filter by category ID")
    p_syn.add_argument("--no-discover", action="store_true", help="Do not pull remote-only pages into local project")
    p_syn.add_argument("--prune-deleted", action="store_true", help="Prune local pages that were deleted on the remote wiki")
    p_syn.add_argument("--dry-run", action="store_true", help="Pull remote changes and preview publish phase without pushing")
    p_syn.add_argument("--no-assets", action="store_true", help="Skip pre-uploading assets during publish phase")
    p_syn.add_argument("--force", action="store_true", help="Bypass optimistic SHA-256 and active UI lock guards during publish")
    p_syn.set_defaults(func=cmd_sync)

    # diff
    p_dif = subparsers.add_parser("diff", help="Diff local document against remote Qwiki state, lock, and discussions")
    p_dif.add_argument("target", help="Relative file path, slug, or shareKey of the document to inspect")
    p_dif.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_dif.add_argument("-p", "--profile", help="Target named profile")
    p_dif.add_argument("--url", help="Override remote Qwiki URL")
    p_dif.add_argument("--key", help="Override remote API key")
    p_dif.set_defaults(func=cmd_diff)

    # upload-assets
    p_ast = subparsers.add_parser("upload-assets", help="Upload assets from assets_dir to remote Qwiki")
    p_ast.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_ast.add_argument("-p", "--profile", help="Target named profile")
    p_ast.add_argument("--url", help="Override remote Qwiki URL")
    p_ast.add_argument("--key", help="Override remote API key")
    p_ast.set_defaults(func=cmd_upload_assets)

    # list
    p_lst = subparsers.add_parser("list", help="List remote chapters and detect duplicates")
    p_lst.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_lst.add_argument("-p", "--profile", help="Target named profile")
    p_lst.add_argument("--url", help="Override remote Qwiki URL")
    p_lst.add_argument("--key", help="Override remote API key")
    p_lst.add_argument("--book-id", help="Filter by category ID")
    p_lst.set_defaults(func=cmd_list)

    # dedup
    p_ddp = subparsers.add_parser("dedup", help="Automatically remove duplicate remote chapters")
    p_ddp.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_ddp.add_argument("-p", "--profile", help="Target named profile")
    p_ddp.add_argument("--url", help="Override remote Qwiki URL")
    p_ddp.add_argument("--key", help="Override remote API key")
    p_ddp.add_argument("--book-id", help="Filter by category ID")
    p_ddp.add_argument("--dry-run", action="store_true", help="Preview duplicates without deleting")
    p_ddp.set_defaults(func=cmd_dedup)

    # reload
    p_rld = subparsers.add_parser("reload", help="Clean purge and reload all canonical documents to remote Qwiki")
    p_rld.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_rld.add_argument("-p", "--profile", help="Target named profile")
    p_rld.add_argument("--url", help="Override remote Qwiki URL")
    p_rld.add_argument("--key", help="Override remote API key")
    p_rld.set_defaults(func=cmd_reload)

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a specific chapter by slug from remote Qwiki")
    p_del.add_argument("slug", help="Slug of the chapter to delete")
    p_del.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_del.add_argument("-p", "--profile", help="Target named profile")
    p_del.add_argument("--url", help="Override remote Qwiki URL")
    p_del.add_argument("--key", help="Override remote API key")
    p_del.add_argument("--book-id", help="Category ID of the chapter")
    p_del.set_defaults(func=cmd_delete)

    # theme
    p_thm = subparsers.add_parser("theme", help="Manage and apply theme CSS stylesheets for site, category, or page")
    thm_sub = p_thm.add_subparsers(dest="theme_action", required=True, help="Theme subcommands")

    def _add_conn_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--manifest", help="Path to qwiki-project.json or project directory")
        sp.add_argument("-p", "--profile", help="Target named profile")
        sp.add_argument("--url", help="Override remote Qwiki URL")
        sp.add_argument("--key", help="Override remote API key")

    p_thm_list = thm_sub.add_parser("list", help="List available remote themes and active site theme")
    _add_conn_args(p_thm_list)
    p_thm_list.set_defaults(func=cmd_theme)

    p_thm_get = thm_sub.add_parser("get", help="Download a theme CSS file from remote Qwiki")
    p_thm_get.add_argument("theme", help="Remote theme filename (e.g. theme-article-modern.css)")
    p_thm_get.add_argument("-o", "--out", help="Write CSS to local file path instead of stdout")
    _add_conn_args(p_thm_get)
    p_thm_get.set_defaults(func=cmd_theme)

    p_thm_up = thm_sub.add_parser("upload", help="Upload a custom theme-*.css file to remote Qwiki")
    p_thm_up.add_argument("file", help="Path to local CSS file")
    p_thm_up.add_argument("--name", help="Override remote theme filename (must match theme-*.css)")
    _add_conn_args(p_thm_up)
    p_thm_up.set_defaults(func=cmd_theme)

    p_thm_app = thm_sub.add_parser("apply", help="Apply a theme CSS file to site, category, or page")
    p_thm_app.add_argument("theme", help="Remote theme name (theme-*.css) or path to local CSS file")
    p_thm_app.add_argument("--site", action="store_true", help="Apply as site-wide default theme")
    p_thm_app.add_argument("--category", help="Apply to a specific category ID")
    p_thm_app.add_argument("--slug", help="Apply to a specific page/chapter slug")
    _add_conn_args(p_thm_app)
    p_thm_app.set_defaults(func=cmd_theme)

    # forms
    p_frm = subparsers.add_parser("forms", help="Automate JSON web form creation/updates and monitor/export form responses")
    frm_sub = p_frm.add_subparsers(dest="forms_action", required=True, help="Form subcommands")

    p_frm_list = frm_sub.add_parser("list", help="List all JSON web forms on remote Qwiki with response counts")
    p_frm_list.add_argument("--book-id", help="Filter by category ID")
    _add_conn_args(p_frm_list)
    p_frm_list.set_defaults(func=cmd_forms)

    p_frm_push = frm_sub.add_parser("push", help="Create or update a JSON web form (.form.json) on remote Qwiki")
    p_frm_push.add_argument("file", help="Path to local .form.json schema file")
    p_frm_push.add_argument("-c", "--category", help="Target category ID (optional if declared in qwiki-project.json)")
    p_frm_push.add_argument("-s", "--slug", help="Override form slug")
    p_frm_push.add_argument("-t", "--title", help="Override form title")
    p_frm_push.add_argument("--force", action="store_true", help="Bypass active lock guard")
    _add_conn_args(p_frm_push)
    p_frm_push.set_defaults(func=cmd_forms)

    p_frm_resp = frm_sub.add_parser("responses", help="Fetch or export form responses (table, json, or csv)")
    p_frm_resp.add_argument("target", help="Form slug, file path, or docId")
    p_frm_resp.add_argument("-f", "--format", choices=["table", "json", "csv"], default="table", help="Output format")
    p_frm_resp.add_argument("--since", help="Filter responses submitted on/after datetime (e.g. '2026-11-20 00:00:00')")
    p_frm_resp.add_argument("--since-id", help="Return only responses submitted after a specific submission ID")
    p_frm_resp.add_argument("-n", "--limit", type=int, help="Maximum number of recent responses to return")
    p_frm_resp.add_argument("-o", "--out", help="Write output to file path instead of stdout")
    _add_conn_args(p_frm_resp)
    p_frm_resp.set_defaults(func=cmd_forms)

    p_frm_watch = frm_sub.add_parser("watch", help="Monitor a form in real time for new responses")
    p_frm_watch.add_argument("target", help="Form slug, file path, or docId")
    p_frm_watch.add_argument("-i", "--interval", type=int, default=15, help="Polling interval in seconds (default: 15)")
    p_frm_watch.add_argument("--since-id", help="Resume watching after a specific submission ID")
    p_frm_watch.add_argument("--max-polls", type=int, help="Stop automatically after N polls (useful for scripts/tests)")
    _add_conn_args(p_frm_watch)
    p_frm_watch.set_defaults(func=cmd_forms)

    p_frm_del = frm_sub.add_parser("delete-response", help="Delete a single form submission by ID")
    p_frm_del.add_argument("target", help="Form slug, file path, or docId")
    p_frm_del.add_argument("--id", required=True, help="Submission ID to delete (e.g. sub_...)")
    _add_conn_args(p_frm_del)
    p_frm_del.set_defaults(func=cmd_forms)

    p_frm_clr = frm_sub.add_parser("clear-responses", help="Clear all responses for a form")
    p_frm_clr.add_argument("target", help="Form slug, file path, or docId")
    _add_conn_args(p_frm_clr)
    p_frm_clr.set_defaults(func=cmd_forms)

    return parser


def main(args: Optional[List[str]] = None) -> int:
    parser = build_parser()
    parsed_args = parser.parse_args(args)

    if not parsed_args.subcommand:
        parser.print_help()
        return 0

    return parsed_args.func(parsed_args)


if __name__ == "__main__":
    sys.exit(main())
