"""Reproducible, polite extractor for Hubble's public gift-card catalog API.

This is a clean reference implementation built from the verified public API
contract. It does not claim to be byte-for-byte identical to an earlier run.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_ROOT = "https://api.myhubble.money"
CATALOG_URL = f"{API_ROOT}/v3/store/products/search"
PAGE_ROOT = "https://offers.myhubble.money/buy-gift-card"
HEADERS = {
    "X-Client-Id": "hubble",
    "X-App-Version": "10000",
    "Accept": "application/json",
    "User-Agent": "HubbleLearningExtractor/1.0 (educational, low-rate requests)",
}
CSV_FIELDS = [
    "rank", "brand_name", "brand_key", "category", "category_id",
    "discount_percentage", "validity_days", "validity_text", "about",
    "how_to_redeem", "restrictions", "terms_and_conditions", "faqs",
    "tips", "source_url",
]


def clean_text(value: Any) -> str | None:
    """Normalize whitespace. Return None instead of inventing missing text."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def unique_nonempty(values: Iterable[Any]) -> list[str]:
    """Keep source order, remove blanks and exact duplicates."""
    values = values or []
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = clean_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def nested(obj: Any, *path: str, default: Any = None) -> Any:
    """Safely read nested dictionaries."""
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


@dataclass
class Config:
    limit: int
    delay: float
    timeout: float
    output_dir: Path


class HubbleClient:
    """HTTP client with retries, backoff and an enforced request delay."""

    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        retry = Retry(
            total=4,
            connect=4,
            read=4,
            status=4,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(HEADERS)
        self.last_request_at = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self.last_request_at
        if elapsed < self.config.delay:
            time.sleep(self.config.delay - elapsed)

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """GET JSON; log failures and return None so one bad brand does not stop all."""
        self._wait()
        try:
            response = self.session.get(url, params=params, timeout=self.config.timeout)
            self.last_request_at = time.monotonic()
            if response.status_code != 200:
                logging.error("HTTP %s for %s", response.status_code, response.url)
                return None
            payload = response.json()
            if not isinstance(payload, dict):
                logging.error("Expected JSON object from %s", response.url)
                return None
            return payload
        except (requests.RequestException, ValueError) as exc:
            self.last_request_at = time.monotonic()
            logging.exception("Request failed for %s: %s", url, exc)
            return None

    def catalog(self) -> list[dict[str, Any]]:
        payload = self.get_json(CATALOG_URL, {"q": "", "limit": self.config.limit, "pageNo": 0})
        products: list[dict[str, Any]] = []
        for section in (payload or {}).get("data", []):
            if isinstance(section, dict):
                products.extend(p for p in section.get("products", []) if isinstance(p, dict))
        return products[: self.config.limit]

    def brand_sources(self, brand_key: str) -> tuple[dict | None, dict | None, dict | None, dict | None]:
        safe_key = quote(brand_key, safe="")
        brand = self.get_json(f"{API_ROOT}/v1/store/products/voucher-product/{safe_key}")
        external_id = clean_text((brand or {}).get("externalId"))
        tnc = redeem = None
        if external_id:
            safe_id = quote(external_id, safe="")
            tnc = self.get_json(f"{API_ROOT}/v1/store/products/voucher-product/{safe_id}/tnc")
            redeem = self.get_json(f"{API_ROOT}/v1/store/products/voucher-product/{safe_id}/how-to-redeem-details")
        else:
            logging.error("No externalId for brand_key=%s; T&C and redemption left null", brand_key)
        extra = self.get_json(f"{API_ROOT}/v1/store/products/voucher-product/{safe_key}/extra-metadata")
        return brand, tnc, redeem, extra


def parse_redeem(redeem: dict | None, brand: dict | None) -> list[dict[str, Any]] | None:
    steps_data = (redeem or {}).get("howToUseSteps")
    if not isinstance(steps_data, list):
        steps_data = nested(brand, "voucherProductMetadata", "howToUseSteps", default=[])
    parsed = []
    for item in steps_data if isinstance(steps_data, list) else []:
        if not isinstance(item, dict):
            continue
        detailed = nested(item, "howToUseInDetail", "steps", default=[])
        steps = unique_nonempty(x.get("description") for x in detailed if isinstance(x, dict))
        if not steps:
            steps = unique_nonempty(nested(item, "howToUseHints", "hints", default=[]))
        parsed.append({
            "mode": clean_text(item.get("retailModeName")) or clean_text(item.get("retailMode")),
            "steps": steps or None,
        })
    return parsed or None


def validity_text(conditions: list[Any], faqs: list[Any], days: Any) -> list[str] | None:
    candidates: list[Any] = []
    candidates.extend(c for c in conditions if "valid" in str(c).lower())
    for faq in faqs:
        if isinstance(faq, dict) and "valid" in f"{faq.get('question', '')} {faq.get('answer', '')}".lower():
            candidates.append(f"{faq.get('question', '')} {faq.get('answer', '')}")
    if days is not None:
        candidates.insert(0, f"{days} days (structured API field)")
    return unique_nonempty(candidates) or None


def transform(rank: int, product: dict[str, Any], brand: dict | None,
              tnc: dict | None, redeem: dict | None, extra: dict | None) -> dict[str, Any]:
    voucher = product.get("voucherProduct") if isinstance(product.get("voucherProduct"), dict) else {}
    metadata = nested(brand, "voucherProductMetadata", default={})
    if not isinstance(metadata, dict):
        metadata = {}
    conditions = metadata.get("conditions") if isinstance(metadata.get("conditions"), list) else []
    faqs = (extra or {}).get("faqs") if isinstance((extra or {}).get("faqs"), list) else []
    key = clean_text(product.get("brandKey"))
    return {
        "rank": rank,
        "brand_name": clean_text((brand or {}).get("name")) or clean_text(voucher.get("title")),
        "brand_key": key,
        "source_url": f"{PAGE_ROOT}/{quote(key, safe='')}" if key else None,
        "category": clean_text((extra or {}).get("categoryTitle")) or clean_text(product.get("category")),
        "category_id": clean_text((extra or {}).get("categoryName")) or clean_text(product.get("category")),
        "discount_percentage": voucher.get("discountPercentage"),
        "validity_days": (extra or {}).get("validityInDays"),
        "validity_text": validity_text(conditions, faqs, (extra or {}).get("validityInDays")),
        "about": clean_text((extra or {}).get("brandDescription"))
                 or clean_text(nested(metadata, "brandLandingPageDetails", "description")),
        "how_to_redeem": parse_redeem(redeem, brand),
        "restrictions": unique_nonempty(conditions) or None,
        "structured_purchase_limits": (brand or {}).get("restrictions"),
        "terms_and_conditions": clean_text((tnc or {}).get("content")),
        "faqs": [
            {"question": clean_text(x.get("question")), "answer": clean_text(x.get("answer"))}
            for x in faqs if isinstance(x, dict)
        ] or None,
        "tips": unique_nonempty(metadata.get("tips", [])) or None,
        "where_to_use": {
            "add_voucher_url": clean_text(metadata.get("addVoucherBrandPageUrl")),
            "store_locator_url": clean_text(metadata.get("storeLocatorUrl")),
        },
    }


def flatten(record: dict[str, Any]) -> dict[str, Any]:
    redeem = record.get("how_to_redeem") or []
    faqs = record.get("faqs") or []
    return {
        "rank": record.get("rank"),
        "brand_name": record.get("brand_name"),
        "brand_key": record.get("brand_key"),
        "category": record.get("category"),
        "category_id": record.get("category_id"),
        "discount_percentage": record.get("discount_percentage"),
        "validity_days": record.get("validity_days"),
        "validity_text": " | ".join(record.get("validity_text") or []),
        "about": record.get("about"),
        "how_to_redeem": " || ".join(
            f"{x.get('mode') or 'General'}: {' -> '.join(x.get('steps') or [])}" for x in redeem
        ),
        "restrictions": " | ".join(record.get("restrictions") or []),
        "terms_and_conditions": record.get("terms_and_conditions"),
        "faqs": " || ".join(f"{x.get('question') or ''} {x.get('answer') or ''}".strip() for x in faqs),
        "tips": " | ".join(record.get("tips") or []),
        "source_url": record.get("source_url"),
    }


def validate(records: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    keys = [x.get("brand_key") for x in records]
    duplicates = sorted({x for x in keys if x and keys.count(x) > 1})
    missing_keys = [x.get("rank") for x in records if not x.get("brand_key")]
    report = {
        "expected_count": expected,
        "actual_count": len(records),
        "unique_brand_keys": len({x for x in keys if x}),
        "duplicate_brand_keys": duplicates,
        "ranks_missing_brand_key": missing_keys,
        "records_with_null_fields": {
            field: sum(1 for x in records if x.get(field) in (None, [], ""))
            for field in ("brand_name", "category", "validity_text", "about", "how_to_redeem", "terms_and_conditions", "faqs")
        },
    }
    report["passed"] = (
        report["actual_count"] == expected
        and report["unique_brand_keys"] == expected
        and not duplicates
        and not missing_keys
    )
    return report


def save_outputs(records: list[dict[str, Any]], report: dict[str, Any], out: Path, mode: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    envelope = {
        "metadata": {
            "generated_at_utc": generated_at,
            "mode": mode,
            "count": len(records),
            "catalog_url": f"{CATALOG_URL}?q=&limit={len(records)}&pageNo=0",
            "note": "Fields unavailable from Hubble are null. Source order is preserved.",
        },
        "brands": records,
    }
    (out / f"hubble-gift-cards-{mode}.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (out / f"hubble-gift-cards-{mode}.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(flatten(x) for x in records)
    (out / f"validation-{mode}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run(config: Config, mode: str) -> int:
    client = HubbleClient(config)
    products = client.catalog()
    logging.info("Catalog returned %d products; requested %d", len(products), config.limit)
    records = []
    for rank, product in enumerate(products, start=1):
        key = clean_text(product.get("brandKey"))
        logging.info("[%d/%d] Fetching %s", rank, config.limit, key or "<missing key>")
        brand, tnc, redeem, extra = client.brand_sources(key) if key else (None, None, None, None)
        records.append(transform(rank, product, brand, tnc, redeem, extra))
    report = validate(records, config.limit)
    save_outputs(records, report, config.output_dir, mode)
    logging.info("Validation: %s", json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract Hubble gift-card catalog data for learning.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--practice", action="store_true", help="Fetch only the first 3 brands.")
    mode.add_argument("--full", action="store_true", help="Fetch the ranked first 100 brands.")
    parser.add_argument("--output-dir", default="output", help="Where JSON/CSV/validation files are written.")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests; minimum 0.35.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    limit, mode = (3, "practice-3") if args.practice else (100, "top100")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    log_file = Path("logs") / f"run-{mode}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
    config = Config(limit=limit, delay=max(args.delay, 0.35), timeout=args.timeout, output_dir=output_dir)
    return run(config, mode)


if __name__ == "__main__":
    raise SystemExit(main())
