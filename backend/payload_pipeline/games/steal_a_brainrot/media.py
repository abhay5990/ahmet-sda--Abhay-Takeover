from __future__ import annotations
import logging
import requests

logger = logging.getLogger(__name__)
FANDOM_API = "https://steal-a-brainrot.fandom.com/api.php"

class SabItemMediaStrategy:
    def fetch_media(self, subject, request):
        if not subject.item_name:
            return []
        url = self._lookup_fandom(subject.item_name)
        if url:
            subject.image_url = url
            return [url]
        return []

    def _lookup_fandom(self, item_name):
        try:
            r = requests.get(FANDOM_API, params={"action":"query","list":"search","srsearch":item_name,"format":"json","srlimit":1}, timeout=8)
            r.raise_for_status()
            results = r.json().get("query", {}).get("search", [])
            if not results: return None
            page_title = results[0]["title"]
            r2 = requests.get(FANDOM_API, params={"action":"query","titles":page_title,"prop":"pageimages","pithumbsize":200,"format":"json"}, timeout=8)
            r2.raise_for_status()
            pages = r2.json().get("query", {}).get("pages", {})
            for page in pages.values():
                thumb = page.get("thumbnail", {})
                if thumb.get("source"): return thumb["source"]
        except Exception as exc:
            logger.debug("Fandom lookup failed for %r: %s", item_name, exc)
        return None
