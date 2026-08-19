import json
import re
from typing import Optional
import httpx
from plugins import SitePlugin

MEPSKING_BASE = "https://www.mepsking.shop"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FPVPrices/1.0; price tracker)",
    "Accept": "text/html,application/xhtml+xml",
}


class MepskingPlugin(SitePlugin):
    name = "mepsking"
    display_name = "MepsKing"
    currency = "$"
    tracks_stock = True

    def can_handle(self, url: str) -> bool:
        return "mepsking.shop" in url

    def extract_handle(self, url: str) -> Optional[str]:
        match = re.search(r'/([^/?#]+)\.html', url)
        return match.group(1) if match else None

    def fetch_product(self, handle: str) -> Optional[dict]:
        url = f"{MEPSKING_BASE}/{handle}.html"
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    return None
                return self._extract_product_group(resp.text)
        except Exception:
            return None

    def _extract_product_group(self, html: str) -> Optional[dict]:
        blocks = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        for block in blocks:
            try:
                data = json.loads(block)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") == "ProductGroup":
                        return item
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def parse_product(self, raw: dict) -> dict:
        product_name = raw.get("name", "")
        product_url = raw.get("url", "")

        handle_match = re.search(r'/([^/?#]+)\.html', product_url)
        handle = handle_match.group(1) if handle_match else raw.get("productGroupID", "")

        image_url = None
        variants_raw = raw.get("hasVariant", [])
        if variants_raw:
            images = variants_raw[0].get("image", [])
            image_url = images[0] if images else None

        variants = []
        for v in variants_raw:
            external_id = v.get("sku", "")

            full_name = v.get("name", "")
            if full_name.startswith(product_name):
                variant_name = full_name[len(product_name):].lstrip("-/ ").strip()
            else:
                variant_name = full_name
            if not variant_name:
                variant_name = "Default"

            offers = v.get("offers", {})
            price = None
            compare_at_price = None
            for spec in offers.get("priceSpecification", []):
                if spec.get("priceType") == "https://schema.org/StrikethroughPrice":
                    compare_at_price = float(spec["price"])
                elif not spec.get("validForMemberTier"):
                    price = float(spec["price"])

            if price is None and offers.get("price") is not None:
                price = float(offers["price"])
            if price is None:
                price = 0.0

            availability = offers.get("availability", "")
            in_stock = "OutOfStock" not in availability and "SoldOut" not in availability

            variants.append({
                "external_variant_id": external_id,
                "name": variant_name,
                "sku": v.get("productId", ""),
                "price": price,
                "compare_at_price": compare_at_price,
                "in_stock": in_stock,
            })

        return {
            "handle": handle,
            "title": product_name,
            "image_url": image_url,
            "product_url": product_url or f"{MEPSKING_BASE}/{handle}.html",
            "variants": variants,
        }

    def extract_pack_count(self, name: str) -> int:
        m = re.search(r'(\d+)\s*(?:pcs|pack)', name, re.IGNORECASE)
        if m:
            n = int(m.group(1))
            return n if n > 1 else 1
        return 1
