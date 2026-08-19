import json
import re
from typing import Optional

import httpx
from plugins import SitePlugin

DFR_BASE = "https://www.drone-fpv-racer.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


class DFRPlugin(SitePlugin):
    name = "dfr"
    display_name = "Drone-FPV-Racer"
    currency = "€"
    tracks_stock = True

    def can_handle(self, url: str) -> bool:
        return "drone-fpv-racer.com" in url

    def extract_handle(self, url: str) -> Optional[str]:
        # Matches /en/{slug}.html (English) or /{slug}.html (French)
        m = re.search(r'/(?:en/)?([^/?#]+)\.html', url)
        return m.group(1) if m else None

    def fetch_product(self, handle: str) -> Optional[dict]:
        # Try English URL first, then bare URL for French handles
        candidates = [
            f"{DFR_BASE}/en/{handle}.html",
            f"{DFR_BASE}/{handle}.html",
        ]
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
                for url in candidates:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        return self._parse_html(resp.text, handle, str(resp.url))
        except Exception:
            return None
        return None

    def _parse_html(self, html: str, handle: str, url: str) -> Optional[dict]:
        product_ld = None
        for block in re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        ):
            try:
                data = json.loads(block)
                if isinstance(data, dict) and data.get("@type") == "Product":
                    product_ld = data
                    break
            except (json.JSONDecodeError, AttributeError):
                continue
        if not product_ld:
            return None

        offers = product_ld.get("offers", {})
        price_str = offers.get("price", "0")
        price = float(price_str) if price_str else 0.0

        # Compare-at price only appears when the product is on sale
        compare_at_price = None
        m = re.search(r'class="regular-price[^"]*"[^>]*>\s*€([\d,.]+)\s*<', html)
        if m:
            compare_at_price = float(m.group(1).replace(",", "."))

        in_stock = "InStock" in offers.get("availability", "")

        id_match = re.search(r'-(\d+)$', handle)
        product_id = id_match.group(1) if id_match else handle

        return {
            "title": product_ld.get("name", ""),
            "sku": product_ld.get("sku", ""),
            "image": product_ld.get("image", ""),
            "price": price,
            "compare_at_price": compare_at_price,
            "in_stock": in_stock,
            "handle": handle,
            "url": url,
            "product_id": product_id,
        }

    def parse_product(self, raw: dict) -> dict:
        return {
            "handle": raw["handle"],
            "title": raw["title"],
            "image_url": raw["image"] or None,
            "product_url": raw["url"],
            "variants": [
                {
                    "external_variant_id": raw["product_id"],
                    "name": "Default",
                    "sku": raw["sku"],
                    "price": raw["price"],
                    "compare_at_price": raw["compare_at_price"],
                    "in_stock": raw["in_stock"],
                }
            ],
        }
