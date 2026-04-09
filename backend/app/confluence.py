"""Confluence Cloud client.

Pulls pages and their PDF attachments from a Confluence space.
Uses Basic Auth with an API token (not OAuth) for simplicity.
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

import requests

logger = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("CONFLUENCE_URL", "").rstrip("/")
        self.email = os.getenv("CONFLUENCE_EMAIL", "")
        self.token = os.getenv("CONFLUENCE_API_TOKEN", "")
        if not all([self.base_url, self.email, self.token]):
            logger.warning("Confluence credentials not configured")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.email and self.token)

    def _get(self, path: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}/wiki/rest/api{path}"
        resp = requests.get(url, auth=(self.email, self.token), timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def get_pages_in_space(self, space_key: str) -> list[dict]:
        """Get all pages in a space."""
        pages = []
        start = 0
        while True:
            resp = self._get(f"/space/{space_key}/content/page", params={
                "start": start, "limit": 50,
                "expand": "children.attachment",
            })
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            pages.extend(results)
            if data.get("size", 0) < 50:
                break
            start += 50
        return pages

    def get_child_pages(self, page_id: str) -> list[dict]:
        """Get child pages under a parent page."""
        resp = self._get(f"/content/{page_id}/child/page", params={"limit": 100})
        return resp.json().get("results", [])

    def get_attachments(self, page_id: str) -> list[dict]:
        """Get all attachments on a page."""
        resp = self._get(f"/content/{page_id}/child/attachment", params={"limit": 100})
        return resp.json().get("results", [])

    def download_attachment(self, download_path: str) -> BytesIO:
        """Download an attachment by its _links.download path."""
        url = f"{self.base_url}/wiki{download_path}"
        resp = requests.get(url, auth=(self.email, self.token), timeout=120)
        resp.raise_for_status()
        return BytesIO(resp.content)

    def find_page_by_title(self, space_key: str, title: str) -> dict | None:
        """Find a page by title in a space."""
        resp = self._get("/content", params={
            "spaceKey": space_key, "title": title, "limit": 1,
        })
        results = resp.json().get("results", [])
        return results[0] if results else None
