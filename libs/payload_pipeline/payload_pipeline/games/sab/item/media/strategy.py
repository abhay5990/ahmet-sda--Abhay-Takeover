from __future__ import annotations
import logging
import requests
logger = logging.getLogger(__name__)
FANDOM_API = "https://steal-a-brainrot.fandom.com/api.php"
class SabItemMediaStrategy:
    def prepare(self, subject, request):
        """Alias for fetch_media — called by the pipeline core."""
        return self.fetch_media(subject, request)
    def fetch_media(self, subject, request):
        # Priority 1: use the image URL already extracted from Eldorado CDN
        if getattr(subject, "image_url", None):
            return [subject.image_url]
        # Priority 2: fall back to Fandom wiki lookup
        if not subject.item_name:
            return []
        url = self._lookup_fandom(subject.item_name)
        if url:
            subject.image_url = url
            return [url]
        return []
    def _lookup_fandom(self, item_name):
        try:
            r = requests.get(
                FANDOM_API,
                params={"action": "query", "list": "search", "srsearch": item_name,
                        "format": "json", "srlimit": 1},
                timeout=5,
            )
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
            if not results:
                return None
            page_title = results[0]["title"]
            r2 = requests.get(
                FANDOM_API,
                params={"action": "query", "titles": page_title, "prop": "pageimages",
                        "pithumbsize": 400, "format": "json"},
                timeout=5,
            )
            r2.raise_for_status()
            pages = r2.json().get("query", {}).get("pages", {})
            for page in pages.values():
                thumb = page.get("thumbnail", {})
                if thumb.get("source"):
                    return thumb["source"]
        except Exception as exc:
            logger.debug("Fandom lookup failed for %r: %s", item_name, exc)
        return None
