import re
from typing import Optional
import httpx
from plugins import SitePlugin

AMPOW_BASE = "https://www.ampow.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FPVPrices/1.0; price tracker)",
    "Accept": "application/json",
}


class AmpowPlugin(SitePlugin):
    name = "ampow"
    display_name = "Ampow"
    currency = "€"
    tracks_stock = True

    def can_handle(self, url: str) -> bool:
        return "ampow.com" in url

    def extract_handle(self, url: str) -> Optional[str]:
        match = re.search(r"/products/([^/?#]+)", url)
        return match.group(1) if match else None

    def fetch_product(self, handle: str) -> Optional[dict]:
        url = f"{AMPOW_BASE}/products/{handle}.json"
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return data.get("product")
        except Exception:
            return None

    def parse_product(self, raw: dict) -> dict:
        image_url = None
        if raw.get("images"):
            image_url = raw["images"][0].get("src")

        variants = []
        for v in raw.get("variants", []):
            price = float(v["price"]) if v.get("price") else 0.0
            compare_at = float(v["compare_at_price"]) if v.get("compare_at_price") else None
            inv_mgmt = v.get("inventory_management")
            inv_policy = v.get("inventory_policy", "deny")
            inv_qty = v.get("inventory_quantity", 0)
            if inv_mgmt is None or inv_policy == "continue":
                in_stock = True
            else:
                in_stock = inv_qty > 0
            variants.append({
                "external_variant_id": str(v["id"]),
                "name": v.get("title", "Default"),
                "sku": v.get("sku", ""),
                "price": price,
                "compare_at_price": compare_at,
                "in_stock": in_stock,
            })

        return {
            "handle": raw["handle"],
            "title": raw["title"],
            "image_url": image_url,
            "product_url": f"{AMPOW_BASE}/products/{raw['handle']}",
            "variants": variants,
        }

    def extract_pack_count(self, name: str) -> int:
        m = re.search(r'(\d+)', name)
        if m:
            n = int(m.group(1))
            return n if n > 0 else 1
        return 1
