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
        )

    return 0 if res.get("success") else 1


def cmd_update(args: argparse.Namespace) -> int:
    """Update a specific document in place by file or slug."""
    manifest = _resolve_manifest(args.manifest)
    target = args.target.strip()

    # Locate document item
    matched_doc: Optional[DocumentItem] = None
    for d in manifest.documents:
        if target in (d.slug, d.file, Path(d.file).name, Path(d.file).stem):
            matched_doc = d
            break

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
        res = publisher.publish_document_item(matched_doc, update=True, dry_run=args.dry_run)
        status_tag = "🔄 Updated in-place" if res.get("updated") else "✨ Created"
        print(f"✅ {status_tag} successfully!")
        print(f"   • Slug: {res.get('slug')}")
        print(f"   • URL:  {res.get('url')}")
        if res.get("shareKey"):
            print(f"   • Share Key: {res.get('shareKey')}")
        return 0
    except Exception as e:
        print(f"❌ Update failed: {e}")
        return 1


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
    p_pub.set_defaults(func=cmd_publish)

    # update
    p_upd = subparsers.add_parser("update", help="Update a specific chapter in place on remote Qwiki")
    p_upd.add_argument("target", help="Relative file path or slug of the document to update")
    p_upd.add_argument("manifest", nargs="?", help="Path to qwiki-project.json or project directory")
    p_upd.add_argument("-p", "--profile", help="Target named profile")
    p_upd.add_argument("--url", help="Override remote Qwiki URL")
    p_upd.add_argument("--key", help="Override remote API key")
    p_upd.add_argument("--dry-run", action="store_true", help="Preview update without network modifications")
    p_upd.set_defaults(func=cmd_update)

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
