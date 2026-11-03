"""
Asset management and image upload / URL rewriting engine for Qwiki Builder.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .client import QwikiClient


class AssetManager:
    """Discovers, uploads, and rewrites relative image assets for Qwiki documents."""

    def __init__(self, client: QwikiClient, assets_dir: Path, cache_file: Optional[Path] = None):
        self.client = client
        self.assets_dir = assets_dir.resolve()
        self.cache_file = cache_file or (self.assets_dir / ".uploaded_assets.json")
        self.upload_cache: Dict[str, str] = self._load_cache()

    def _load_cache(self) -> Dict[str, str]:
        if self.cache_file.is_file():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(self.upload_cache, indent=2), encoding="utf-8")
        except Exception:
            pass

    def upload_file(self, file_path: Path) -> str:
        """
        Uploads a single asset file to Qwiki. Returns the remote URL or uploaded relative path.
        Uses cache if file was already uploaded and modified timestamp hasn't changed.
        """
        file_path = file_path.resolve()
        cache_key = f"{file_path.name}:{file_path.stat().st_mtime}"

        if cache_key in self.upload_cache:
            return self.upload_cache[cache_key]

        res = self.client.upload_image(file_path)
        # API returns 'url' or 'file'
        remote_url = res.get("url") or res.get("file") or res.get("path") or f"uploads/{file_path.name}"
        self.upload_cache[cache_key] = remote_url
        self._save_cache()
        return remote_url

    def upload_all_in_assets_dir(self) -> Dict[str, str]:
        """Uploads all supported images and assets found in the assets directory."""
        if not self.assets_dir.is_dir():
            return {}

        uploaded: Dict[str, str] = {}
        extensions = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.svg", "*.gif")
        for ext in extensions:
            for f in self.assets_dir.rglob(ext):
                if f.name.startswith("."):
                    continue
                try:
                    url = self.upload_file(f)
                    uploaded[f.name] = url
                except Exception as e:
                    print(f"  ⚠️ Warning: Failed to upload asset {f.name}: {e}")

        return uploaded

    def process_content_images(
        self,
        content: str,
        doc_dir: Path,
        auto_upload: bool = True,
    ) -> Tuple[str, List[str]]:
        """
        Scans markdown/html content for image references. If local files exist,
        uploads them (if auto_upload=True) and rewrites paths to remote URLs.
        Returns (rewritten_content, list_of_referenced_images).
        """
        referenced: List[str] = []

        def replace_md_image(match: re.Match) -> str:
            alt = match.group(1)
            raw_path = match.group(2).strip()

            # Skip remote URLs
            if re.match(r"^https?://", raw_path, re.IGNORECASE) or raw_path.startswith("data:"):
                return match.group(0)

            clean_path = raw_path.split("?")[0].split("#")[0]
            referenced.append(clean_path)

            if not auto_upload:
                return match.group(0)

            # Resolve local path relative to doc_dir or assets_dir
            resolved_file = None
            cand1 = (doc_dir / clean_path).resolve()
            cand2 = (self.assets_dir / clean_path).resolve()
            cand3 = (self.assets_dir / Path(clean_path).name).resolve()

            for cand in (cand1, cand2, cand3):
                if cand.is_file():
                    resolved_file = cand
                    break

            if resolved_file:
                try:
                    remote_url = self.upload_file(resolved_file)
                    return f"![{alt}]({remote_url})"
                except Exception as e:
                    print(f"  ⚠️ Image upload failed for {clean_path}: {e}")

            return match.group(0)

        def replace_html_img(match: re.Match) -> str:
            prefix = match.group(1)
            raw_path = match.group(2).strip()
            suffix = match.group(3)

            if re.match(r"^https?://", raw_path, re.IGNORECASE) or raw_path.startswith("data:"):
                return match.group(0)

            clean_path = raw_path.split("?")[0].split("#")[0]
            referenced.append(clean_path)

            if not auto_upload:
                return match.group(0)

            resolved_file = None
            cand1 = (doc_dir / clean_path).resolve()
            cand2 = (self.assets_dir / clean_path).resolve()
            cand3 = (self.assets_dir / Path(clean_path).name).resolve()

            for cand in (cand1, cand2, cand3):
                if cand.is_file():
                    resolved_file = cand
                    break

            if resolved_file:
                try:
                    remote_url = self.upload_file(resolved_file)
                    return f"{prefix}{remote_url}{suffix}"
                except Exception as e:
                    print(f"  ⚠️ HTML image upload failed for {clean_path}: {e}")

            return match.group(0)

        # Process Markdown images: ![alt](path)
        processed = re.sub(r"!\[(.*?)\]\((.*?)\)", replace_md_image, content)

        # Process HTML img tags: <img ... src="..." ...>
        processed = re.sub(
            r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'][^>]*?>)',
            replace_html_img,
            processed,
            flags=re.IGNORECASE,
        )

        return processed, referenced
