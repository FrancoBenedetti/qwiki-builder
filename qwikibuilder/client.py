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
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


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

        # Resolve publish endpoint
        if self.base_url.endswith("api/publish.php"):
            self.publish_endpoint = self.base_url
        else:
            self.publish_endpoint = f"{self.base_url}/api/publish.php"

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
                try:
                    parsed = json.loads(err_body)
                    if isinstance(parsed, dict) and "error" in parsed:
                        err_msg = str(parsed["error"])
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
                ) from e
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
            payload["parent"] = parent
        res = self.post(payload)
        if not res.get("success"):
            raise QwikiClientError(res.get("error", f"Failed to create category '{category_id}'"))
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
        public_shareable: bool = True,
        update: bool = True,
        overwrite: bool = True,
        approver: Optional[str] = None,
        note: Optional[str] = None,
        clean_source: bool = False,
    ) -> Dict[str, Any]:
        """Publishes or updates a document (markdown or html) on Qwiki."""
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
