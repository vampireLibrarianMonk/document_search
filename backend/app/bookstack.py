"""BookStack REST API client.

Pulls books, chapters, pages, and their PDF attachments from a
local BookStack instance. Used as the local dev stand-in for Confluence.

BookStack API docs: https://demo.bookstackapp.com/api/docs
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

import requests

logger = logging.getLogger(__name__)


class BookStackClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("BOOKSTACK_URL", "http://bookstack:80").rstrip("/")
        self.token_id = os.getenv("BOOKSTACK_TOKEN_ID", "")
        self.token_secret = os.getenv("BOOKSTACK_TOKEN_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token_id and self.token_secret)

    def _headers(self) -> dict:
        return {"Authorization": f"Token {self.token_id}:{self.token_secret}"}

    def _get(self, path: str, **params) -> dict:
        resp = requests.get(
            f"{self.base_url}/api{path}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -- Shelves / Books / Pages --

    def list_books(self) -> list[dict]:
        """List all books."""
        return self._get("/books")["data"]

    def list_pages(self, book_id: int | None = None) -> list[dict]:
        """List pages, optionally filtered to a book."""
        params = {}
        if book_id is not None:
            params["filter[book_id]"] = book_id
        return self._get("/pages", **params)["data"]

    def get_page(self, page_id: int) -> dict:
        return self._get(f"/pages/{page_id}")

    # -- Attachments --

    def list_attachments(self, page_id: int | None = None) -> list[dict]:
        """List attachments, optionally filtered to a page."""
        data = self._get("/attachments")["data"]
        if page_id is not None:
            data = [a for a in data if a.get("uploaded_to") == page_id]
        return data

    def download_attachment(self, attachment_id: int) -> tuple[str, BytesIO]:
        """Download an attachment. Returns (filename, content)."""
        resp = requests.get(
            f"{self.base_url}/api/attachments/{attachment_id}",
            headers=self._headers(),
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("name", f"attachment_{attachment_id}")
        content = data.get("content", "")

        # If it's a file attachment, content is base64 encoded
        if data.get("external") is False or data.get("extension"):
            import base64
            return name, BytesIO(base64.b64decode(content))

        # Otherwise it's a link, not a file
        return name, BytesIO(content.encode())

    def get_all_pdf_attachments(self) -> list[dict]:
        """Get all attachments that look like PDFs."""
        attachments = self._get("/attachments")["data"]
        return [
            a for a in attachments
            if a.get("name", "").lower().endswith(".pdf")
            or a.get("extension", "").lower() == "pdf"
        ]

    # -- Create / Write --

    def _post(self, path: str, **kwargs) -> dict:
        resp = requests.post(
            f"{self.base_url}/api{path}",
            headers=self._headers(),
            timeout=30,
            **kwargs,
        )
        resp.raise_for_status()
        return resp.json()

    def find_or_create_book(self, name: str) -> int:
        """Find a book by name, or create it. Returns book ID."""
        for book in self.list_books():
            if book["name"].lower() == name.lower():
                return book["id"]
        result = self._post("/books", json={"name": name})
        logger.info("Created BookStack book: %s (id=%d)", name, result["id"])
        return result["id"]

    def find_or_create_page(self, book_id: int, title: str) -> int:
        """Find a page by title in a book, or create it. Returns page ID."""
        for page in self.list_pages(book_id):
            if page["name"].lower() == title.lower():
                return page["id"]
        result = self._post("/pages", json={
            "book_id": book_id,
            "name": title,
            "html": f"<p>Documents filed under: {title}</p>",
        })
        logger.info("Created BookStack page: %s (id=%d)", title, result["id"])
        return result["id"]

    def upload_attachment(self, page_id: int, filename: str, content: bytes) -> dict:
        """Attach a file to a page."""
        return self._post(
            "/attachments",
            data={"name": filename, "uploaded_to": str(page_id)},
            files={"file": (filename, content)},
        )

    def _delete(self, path: str) -> None:
        resp = requests.delete(
            f"{self.base_url}/api{path}",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()

    def delete_attachment_by_name(self, filename: str) -> int:
        """Delete all attachments matching a filename. Returns count deleted."""
        deleted = 0
        for att in self._get("/attachments")["data"]:
            if att.get("name") == filename:
                self._delete(f"/attachments/{att['id']}")
                deleted += 1
        return deleted

    def delete_all_attachments(self) -> int:
        """Delete all attachments. Returns count deleted."""
        atts = self._get("/attachments")["data"]
        for att in atts:
            self._delete(f"/attachments/{att['id']}")
        return len(atts)

    def delete_empty_pages_and_books(self):
        """Clean up pages with no attachments and books with no pages."""
        for page in self._get("/pages")["data"]:
            atts = [a for a in self._get("/attachments")["data"] if a.get("uploaded_to") == page["id"]]
            if not atts:
                self._delete(f"/pages/{page['id']}")
        for book in self.list_books():
            pages = self.list_pages(book["id"])
            if not pages:
                self._delete(f"/books/{book['id']}")
