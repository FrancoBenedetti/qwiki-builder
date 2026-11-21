"""
API Client for Standalone Qwiki remote management and publishing.
"""

from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


class QwikiClientError(Exception):
    """Raised when an API request to Qwiki fails."""
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        error_code: Optional[str] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.error_code = error_code
        self.response_data = response_data or {}


class QwikiClient:
    """Headless REST API client for Standalone Qwiki."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "QwikiBuilder/1.0",
    ):
        self.base_url = base_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent

        # Resolve publish and llm endpoints
        if self.base_url.endswith("api/publish.php"):
            self.publish_endpoint = self.base_url
            self.llm_endpoint = self.base_url[:-len("api/publish.php")] + "api/llm.php"
        else:
            self.publish_endpoint = f"{self.base_url}/api/publish.php"
            self.llm_endpoint = f"{self.base_url}/api/llm.php"

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "X-API-KEY": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }
        if extra:
            headers.update(extra)
        return headers

    def post(
        self,
        payload: Dict[str, Any],
        timeout: Optional[int] = None,
        retries: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Sends an authenticated form-encoded POST request to Qwiki API."""
        encoded_data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            self.publish_endpoint,
            data=encoded_data,
            headers=self._headers({"Content-Type": "application/x-www-form-urlencoded"}),
        )

        effective_retries = retries if retries is not None else self.max_retries
        effective_timeout = timeout if timeout is not None else self.timeout

        last_error: Optional[Exception] = None

        for attempt in range(1, effective_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as jde:
                        raise QwikiClientError(
                            f"Invalid JSON returned by Qwiki endpoint: {raw[:300]}",
                            status_code=resp.status,
                            response_body=raw,
                        ) from jde

                    if not isinstance(data, dict):
                        raise QwikiClientError(f"Unexpected response type from Qwiki: {type(data)}")

                    return data
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                err_msg = err_body
                err_code = None
                parsed_data: Dict[str, Any] = {}
                try:
                    parsed = json.loads(err_body)
                    if isinstance(parsed, dict):
                        parsed_data = parsed
                        if "error" in parsed:
                            err_msg = str(parsed["error"])
                        if "code" in parsed:
                            err_code = str(parsed["code"])
                except Exception:
                    pass

                # Retry on rate limiting, server errors, or transient issues
                if attempt < effective_retries and (e.code in (403, 429, 500, 502, 503, 504) or "temporarily" in err_msg.lower()):
                    time.sleep(attempt * 1.5)
                    continue

                raise QwikiClientError(
                    f"HTTP {e.code}: {err_msg}",
                    status_code=e.code,
                    response_body=err_body,
                    error_code=err_code,
                    response_data=parsed_data,
                ) from e
            except QwikiClientError:
                raise
            except urllib.error.URLError as e:
                last_error = e
                if attempt < effective_retries:
                    time.sleep(attempt * 1.5)
                    continue
                raise QwikiClientError(f"Connection failed to {self.publish_endpoint}: {e}") from e
            except Exception as e:
                last_error = e
                if attempt < effective_retries:
                    time.sleep(attempt * 1.5)
                    continue
                raise QwikiClientError(f"API request failed: {e}") from e

        raise QwikiClientError(f"API request failed after {effective_retries} attempts: {last_error}")

    def list_categories(self) -> List[Dict[str, Any]]:
        """Lists all categories/books on the remote wiki."""
        res = self.post({"action": "list_categories"})
        if not res.get("success"):
            raise QwikiClientError(res.get("error", "Failed to list categories"))
        return res.get("categories", [])

    def create_category(
        self,
        category_id: str,
        title: str,
        description: str = "",
        parent: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Creates or registers a category on the remote wiki."""
        payload = {
            "action": "create_category",
            "id": category_id,
            "title": title,
        }
        if description:
            payload["description"] = description
        if parent:
            payload["parentId"] = parent
        if theme is not None:
            payload["theme"] = theme
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to create category '{category_id}'"))
        return res

    def update_category(
        self,
        category_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        theme: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Updates an existing category's metadata or theme on the remote wiki."""
        payload: Dict[str, Any] = {
            "action": "update_category",
            "id": category_id,
        }
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if theme is not None:
            payload["theme"] = theme
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to update category '{category_id}'"))
        return res

    def list_chapters(self, book_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists chapters registered on remote wiki, optionally filtered by category book_id."""
        payload = {"action": "list_chapters"}
        if book_id:
            payload["bookId"] = book_id
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", "Failed to list chapters"))
        return res.get("chapters", [])

    def get_tree(self, book_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieves the full remote navigation tree (recursive categories + chapters with docId and sha256).
        Falls back to list_categories + list_chapters if the server runs an older version without get_tree.
        """
        payload: Dict[str, Any] = {"action": "get_tree"}
        if book_id:
            payload["bookId"] = book_id
        try:
            res = self.post(payload)
            if not res.get("success"):
                raise QwikiClientError(res.get("error", "Failed to retrieve remote tree"))
            if "categories" not in res:
                res["categories"] = self.list_categories()
            return res
        except QwikiClientError as e:
            if e.status_code == 400 and "bookId, title, and content are required" in str(e):
                cats = self.list_categories()
                chaps = self.list_chapters(book_id=book_id)
                return {
                    "success": True,
                    "categories": cats,
                    "chapters": chaps,
                    "total": len(chaps),
                }
            raise

    def get_document(
        self,
        slug: Optional[str] = None,
        share_key: Optional[str] = None,
        doc_id: Optional[str] = None,
        book_id: Optional[str] = None,
        file_path: Optional[str] = None,
        include_comments: bool = True,
        include_talk: bool = True,
    ) -> Dict[str, Any]:
        """
        Pulls a remote document's raw content, SHA-256, lock state, metadata,
        comments, and talk page via api/publish.php?action=get_doc.
        Falls back to api/llm.php if the remote server runs an older version without get_doc.
        """
        payload: Dict[str, Any] = {
            "action": "get_doc",
            "include_comments": "1" if include_comments else "0",
            "include_talk": "1" if include_talk else "0",
        }
        if slug:
            payload["slug"] = slug
        if share_key:
            payload["shareKey"] = share_key
        if doc_id:
            payload["docId"] = doc_id
        if book_id:
            payload["bookId"] = book_id
        if file_path:
            payload["file"] = file_path

        try:
            res = self.post(payload)
            if not res.get("success") or "document" not in res:
                raise QwikiClientError(res.get("error", f"Failed to pull document '{slug or share_key or doc_id or file_path}'"))
            return res["document"]
        except QwikiClientError as e:
            # Older Standalone Qwiki servers fall through unknown actions to publish_doc validation
            if (
                slug
                and e.status_code == 400
                and "bookId, title, and content are required" in str(e)
            ):
                return self._get_document_via_llm_fallback(
                    slug=slug,
                    include_comments=include_comments,
                    include_talk=include_talk,
                )
            raise

    def _get_document_via_llm_fallback(
        self,
        slug: str,
        include_comments: bool = True,
        include_talk: bool = True,
    ) -> Dict[str, Any]:
        """Fallback pull via api/llm.php for older Standalone Qwiki versions."""
        import hashlib

        query = urllib.parse.urlencode({
            "mode": "doc",
            "slug": slug,
            "include_comments": "1" if include_comments else "0",
            "include_talk": "1" if include_talk else "0",
        })
        req = urllib.request.Request(
            f"{self.llm_endpoint}?{query}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise QwikiClientError(f"HTTP {e.code} from api/llm.php: {err_body}", status_code=e.code, response_body=err_body) from e

        if not data.get("success") or "document" not in data:
            raise QwikiClientError(data.get("error", f"Failed to pull '{slug}' via api/llm.php"))

        doc = data["document"]
        content = doc.get("content", "")
        return {
            "docId": "",
            "bookId": doc.get("category", ""),
            "slug": doc.get("slug", slug),
            "title": doc.get("title", ""),
            "type": doc.get("type", "markdown"),
            "file": "",
            "status": "published",
            "description": doc.get("description", ""),
            "shareKey": "",
            "url": doc.get("url", ""),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "dateModified": doc.get("date_modified", ""),
            "lock": {"locked": False},
            "content": content,
            "commentsEnabled": doc.get("comments_enabled", False),
            "commentsCount": len(doc.get("comments") or []),
            "comments": doc.get("comments") or [],
            "talkEnabled": doc.get("talk_enabled", False),
            "talkTopicsCount": len(doc.get("talk") or []),
            "talkTopics": doc.get("talk") or [],
            "talkRaw": doc.get("talk_raw", ""),
            "_fallback_llm_api": True,
        }

    def publish_document(
        self,
        book_id: str,
        title: str,
        content: str,
        slug: Optional[str] = None,
        doc_type: str = "markdown",
        status: str = "published",
        description: str = "",
        share_key: Optional[str] = None,
        doc_id: Optional[str] = None,
        public_shareable: bool = True,
        update: bool = True,
        overwrite: bool = True,
        approver: Optional[str] = None,
        note: Optional[str] = None,
        clean_source: bool = False,
        expected_sha256: Optional[str] = None,
        force: bool = False,
        theme: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Publishes or updates a document (markdown, html, or form) on Qwiki."""
        payload: Dict[str, Any] = {
            "bookId": book_id,
            "title": title,
            "content": content,
            "type": doc_type,
            "status": status,
        }
        if slug:
            payload["slug"] = slug
        if description:
            payload["description"] = description
        if share_key:
            payload["shareKey"] = share_key
        if doc_id:
            payload["docId"] = doc_id
        if not public_shareable:
            payload["publicShareable"] = "0"
        if update:
            payload["update"] = "true"
        if overwrite:
            payload["overwrite"] = "true"
        if approver:
            payload["approver"] = approver
        if note:
            payload["note"] = note
        if clean_source:
            payload["clean_source"] = "1"
        if expected_sha256:
            payload["expectedSha256"] = expected_sha256
        if force:
            payload["force"] = "1"
        if theme is not None:
            payload["theme"] = theme

        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to publish document '{title}' in [{book_id}]"))
        return res

    def delete_chapter(self, slug: str, book_id: Optional[str] = None) -> Dict[str, Any]:
        """Deletes a chapter from the remote wiki by slug."""
        payload = {
            "action": "delete_chapter",
            "slug": slug,
        }
        if book_id:
            payload["bookId"] = book_id
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to delete chapter '{slug}'"))
        return res

    def list_themes(self) -> Dict[str, Any]:
        """Lists available theme CSS files and the active site theme on the remote wiki."""
        res = self.post({"action": "list_themes"})
        if not res.get("success"):
            raise QwikiClientError(res.get("error", "Failed to list themes"))
        return res

    def get_theme(self, theme: str) -> Dict[str, Any]:
        """Downloads a theme CSS file's content from the remote wiki."""
        res = self.post({"action": "get_theme", "theme": theme})
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to get theme '{theme}'"))
        return res

    def save_theme(self, theme: str, css_content: str) -> Dict[str, Any]:
        """Uploads or updates a custom theme CSS file on the remote wiki."""
        import base64

        encoded = base64.b64encode(css_content.encode("utf-8")).decode("ascii")
        res = self.post({
            "action": "save_theme",
            "theme": theme,
            "content_base64": encoded,
        })
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to save theme '{theme}'"))
        return res

    def set_site_theme(self, theme: str) -> Dict[str, Any]:
        """Sets the site-wide default theme on the remote wiki."""
        res = self.post({"action": "set_site_theme", "theme": theme})
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to set site theme '{theme}'"))
        return res

    def set_status(
        self,
        share_key: str,
        status: str,
        approver: str = "QwikiBuilder",
        note: str = "",
        clean_source: bool = False,
    ) -> Dict[str, Any]:
        """Updates the publication lifecycle status of a document."""
        payload = {
            "action": "set_status",
            "shareKey": share_key,
            "status": status,
            "approver": approver,
            "note": note,
        }
        if clean_source:
            payload["clean_source"] = "1"
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to set status on shareKey '{share_key}'"))
        return res

    def list_forms(self, book_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists all JSON web forms on the remote wiki along with submission counts."""
        payload: Dict[str, Any] = {"action": "list_forms"}
        if book_id:
            payload["bookId"] = book_id
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", "Failed to list forms"))
        return res.get("forms", [])

    def get_form_submissions(
        self,
        slug: Optional[str] = None,
        doc_id: Optional[str] = None,
        share_key: Optional[str] = None,
        book_id: Optional[str] = None,
        file_path: Optional[str] = None,
        since: Optional[str] = None,
        since_id: Optional[str] = None,
        limit: Optional[int] = None,
        output_format: str = "json",
    ) -> Dict[str, Any]:
        """Retrieves submissions (and form schema) or CSV export for a remote JSON web form."""
        payload: Dict[str, Any] = {
            "action": "get_form_submissions",
            "format": output_format,
        }
        if slug:
            payload["slug"] = slug
        if doc_id:
            payload["docId"] = doc_id
        if share_key:
            payload["shareKey"] = share_key
        if book_id:
            payload["bookId"] = book_id
        if file_path:
            payload["file"] = file_path
        if since:
            payload["since"] = since
        if since_id:
            payload["since_id"] = since_id
        if limit is not None and limit > 0:
            payload["limit"] = str(limit)

        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to get submissions for form '{slug or doc_id or file_path}'"))
        return res

    def delete_form_submission(
        self,
        submission_id: str,
        slug: Optional[str] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deletes a single submission record by ID from a remote JSON web form."""
        payload: Dict[str, Any] = {
            "action": "delete_form_submission",
            "id": submission_id,
        }
        if slug:
            payload["slug"] = slug
        if doc_id:
            payload["docId"] = doc_id
        if file_path:
            payload["file"] = file_path
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to delete submission '{submission_id}'"))
        return res

    def clear_form_submissions(
        self,
        slug: Optional[str] = None,
        doc_id: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Clears all submission records from a remote JSON web form."""
        payload: Dict[str, Any] = {
            "action": "clear_form_submissions",
        }
        if slug:
            payload["slug"] = slug
        if doc_id:
            payload["docId"] = doc_id
        if file_path:
            payload["file"] = file_path
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to clear submissions for form '{slug or doc_id or file_path}'"))
        return res

    def download_remote_asset(self, rel_url: str, dest_path: Path) -> Path:
        """Downloads a remote asset (e.g. uploads/images/...) to a local destination path."""
        clean_rel = rel_url.lstrip("/")
        full_url = f"{self.base_url}/{clean_rel}"
        req = urllib.request.Request(full_url, headers=self._headers())
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            dest_path.write_bytes(resp.read())
        return dest_path

    def upload_image(self, file_path: Path) -> Dict[str, Any]:
        """
        Uploads an image asset to Qwiki via multipart/form-data.
        Returns the API response containing the uploaded relative URL or absolute URL.
        """
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")

        boundary = f"----QwikiBuilderBoundary{secrets.token_hex(16)}"
        filename = file_path.name
        ext = file_path.suffix.lower()

        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".gif": "image/gif",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".ogg": "video/ogg",
            ".ogv": "video/ogg",
            ".mov": "video/quicktime",
            ".pdf": "application/pdf",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        body_bytes = bytearray()
        # action field
        body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
        body_bytes.extend(b'Content-Disposition: form-data; name="action"\r\n\r\n')
        body_bytes.extend(b"upload_image\r\n")

        # image / asset file part
        body_bytes.extend(f"--{boundary}\r\n".encode("utf-8"))
        body_bytes.extend(
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode("utf-8")
        )
        body_bytes.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body_bytes.extend(file_path.read_bytes())
        body_bytes.extend(b"\r\n")

        # end boundary
        body_bytes.extend(f"--{boundary}--\r\n".encode("utf-8"))

        req = urllib.request.Request(
            self.publish_endpoint,
            data=bytes(body_bytes),
            headers=self._headers({
                "Content-Type": f"multipart/form-data; boundary={boundary}"
            }),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                res = json.loads(raw)
                if not res.get("success"):
                    raise QwikiClientError(res.get("error", f"Upload failed for {filename}"))
                return res
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise QwikiClientError(f"HTTP {e.code} during image/asset upload: {err_body}") from e
        except Exception as e:
            raise QwikiClientError(f"Image/asset upload error: {e}") from e

    def upload_asset(self, file_path: Path) -> Dict[str, Any]:
        """Alias for upload_image supporting images, generated graphics, and videos."""
        return self.upload_image(file_path)
