#!/usr/bin/env python3
"""
Migrate ovoprice.db (ampow.com / Shopify) records into the fpvprices.db.

Schema differences handled:
  - Variant.shopify_variant_id (INTEGER) → Variant.external_variant_id (TEXT)
  - Product.site is set to 'ampow' for all migrated rows
  - PriceCheck.in_stock is set to 1 (True) — ovoprice did not track stock

The script is idempotent: re-running it will not create duplicates.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_SOURCE = HERE.parent / "ovoprice" / "ovoprice.db"
DEFAULT_TARGET = HERE / "fpvprices.db"


def migrate(source_path: Path, target_path: Path, *, dry_run: bool = False) -> None:
    if not source_path.exists():
        sys.exit(f"Source database not found: {source_path}")
    if not target_path.exists():
        sys.exit(f"Target database not found: {target_path}")

    src = sqlite3.connect(source_path)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(target_path)
    dst.row_factory = sqlite3.Row

    products_added = variants_added = checks_added = 0
    products_skipped = variants_skipped = checks_skipped = 0

    try:
        for src_product in src.execute("SELECT * FROM products ORDER BY created_at").fetchall():
            handle = src_product["handle"]

            dst_row = dst.execute(
                "SELECT id, site FROM products WHERE handle = ?", (handle,)
            ).fetchone()

            if dst_row is not None:
                if dst_row["site"] != "ampow":
                    print(f"  CONFLICT  handle='{handle}' already exists with site='{dst_row['site']}' — skipping")
                    continue
                dst_product_id = dst_row["id"]
                print(f"  exists    {src_product['title']} ({handle})")
                products_skipped += 1
            else:
                print(f"  + product {src_product['title']} ({handle})")
                if not dry_run:
                    dst.execute(
                        """INSERT INTO products
                               (handle, title, image_url, product_url, site, created_at, last_checked_at)
                           VALUES (?, ?, ?, ?, 'ampow', ?, ?)""",
                        (
                            handle,
                            src_product["title"],
                            src_product["image_url"],
                            src_product["product_url"],
                            src_product["created_at"],
                            src_product["last_checked_at"],
                        ),
                    )
                    dst_product_id = dst.execute(
                        "SELECT id FROM products WHERE handle = ?", (handle,)
                    ).fetchone()["id"]
                else:
                    dst_product_id = None
                products_added += 1

            src_variants = src.execute(
                "SELECT * FROM variants WHERE product_id = ?", (src_product["id"],)
            ).fetchall()

            for src_variant in src_variants:
                external_id = str(src_variant["shopify_variant_id"])

                if dst_product_id is not None:
                    dst_variant_row = dst.execute(
                        "SELECT id FROM variants WHERE product_id = ? AND external_variant_id = ?",
                        (dst_product_id, external_id),
                    ).fetchone()
                else:
                    dst_variant_row = None

                if dst_variant_row is not None:
                    dst_variant_id = dst_variant_row["id"]
                    variants_skipped += 1
                else:
                    print(f"    + variant {src_variant['name']} (id={external_id})")
                    if not dry_run and dst_product_id is not None:
                        dst.execute(
                            """INSERT INTO variants
                                   (product_id, external_variant_id, name, sku, tracked, created_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                dst_product_id,
                                external_id,
                                src_variant["name"],
                                src_variant["sku"],
                                src_variant["tracked"],
                                src_variant["created_at"],
                            ),
                        )
                        dst_variant_id = dst.execute(
                            "SELECT id FROM variants WHERE product_id = ? AND external_variant_id = ?",
                            (dst_product_id, external_id),
                        ).fetchone()["id"]
                    else:
                        dst_variant_id = None
                    variants_added += 1

                src_checks = src.execute(
                    "SELECT * FROM price_checks WHERE variant_id = ? ORDER BY checked_at",
                    (src_variant["id"],),
                ).fetchall()

                for src_check in src_checks:
                    if dst_variant_id is not None:
                        existing = dst.execute(
                            "SELECT id FROM price_checks WHERE variant_id = ? AND checked_at = ?",
                            (dst_variant_id, src_check["checked_at"]),
                        ).fetchone()
                    else:
                        existing = None

                    if existing is not None:
                        checks_skipped += 1
                    else:
                        if not dry_run and dst_variant_id is not None:
                            dst.execute(
                                """INSERT INTO price_checks
                                       (variant_id, price, compare_at_price, in_stock, checked_at)
                                   VALUES (?, ?, ?, 1, ?)""",
                                (
                                    dst_variant_id,
                                    src_check["price"],
                                    src_check["compare_at_price"],
                                    src_check["checked_at"],
                                ),
                            )
                        checks_added += 1

        if not dry_run:
            dst.commit()

    finally:
        src.close()
        dst.close()

    tag = "[DRY RUN] " if dry_run else ""
    print(f"\n{tag}Migration complete:")
    print(f"  products : {products_added} added, {products_skipped} already present")
    print(f"  variants : {variants_added} added, {variants_skipped} already present")
    print(f"  checks   : {checks_added} added, {checks_skipped} already present")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ovoprice.db into fpvprices.db")
    parser.add_argument("source", nargs="?", type=Path, default=DEFAULT_SOURCE,
                        help=f"Path to ovoprice.db (default: {DEFAULT_SOURCE})")
    parser.add_argument("target", nargs="?", type=Path, default=DEFAULT_TARGET,
                        help=f"Path to fpvprices.db (default: {DEFAULT_TARGET})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be migrated without writing anything")
    args = parser.parse_args()

    print(f"Source : {args.source}")
    print(f"Target : {args.target}")
    if args.dry_run:
        print("Mode   : DRY RUN — no changes will be written")
    print()

    migrate(args.source, args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
