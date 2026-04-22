from __future__ import annotations

import logging
import sqlite3

import requests

from src.db.repository import insert_price
from src.ingest.open_food_facts import sync_product_by_code
from src.normalize.names import build_food_id, coerce_iso8601
from src.normalize.units import normalize_mass_to_g, price_per_g

LOGGER = logging.getLogger(__name__)
USER_AGENT = "nutrition-database/1.0 (local@example.invalid)"
PRODUCTS_URL = "https://prices.openfoodfacts.org/api/v1/products"
PRICES_URL = "https://prices.openfoodfacts.org/api/v1/prices"


def sync_prices_for_product(
    conn: sqlite3.Connection,
    product_code: str,
    session: requests.Session | None = None,
) -> int:
    client = session or requests.Session()
    food_id = build_food_id("off", product_code)
    if conn.execute("SELECT 1 FROM foods WHERE food_id = ?", (food_id,)).fetchone() is None:
        sync_product_by_code(conn, product_code, session=client)
    product_payload = client.get(
        PRODUCTS_URL,
        params={"code": product_code},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    product_payload.raise_for_status()
    product_items = product_payload.json().get("items", [])
    product_info = product_items[0] if product_items else {}
    quantity_value = product_info.get("product_quantity")
    quantity_unit = product_info.get("product_quantity_unit")
    prices_response = client.get(
        PRICES_URL,
        params={"product_code": product_code, "size": 100},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    prices_response.raise_for_status()
    payload = prices_response.json()
    imported = 0
    for item in payload.get("items", []):
        currency = str(item.get("currency") or "").upper()
        if currency != "JPY":
            continue
        product = item.get("product") or {}
        record_quantity_value = product.get("product_quantity", quantity_value)
        record_quantity_unit = product.get("product_quantity_unit", quantity_unit)
        if record_quantity_value is None or not record_quantity_unit:
            continue
        price_value = item.get("price")
        if price_value is None:
            continue
        grams = normalize_mass_to_g(float(record_quantity_value), record_quantity_unit)
        insert_price(
            conn,
            food_id=food_id,
            price_yen=float(price_value),
            quantity_value=float(record_quantity_value),
            quantity_unit=str(record_quantity_unit),
            price_per_g=price_per_g(float(price_value), float(record_quantity_value), str(record_quantity_unit))
            if grams is not None
            else None,
            observed_at=coerce_iso8601(item.get("date") or item.get("updated") or item.get("created")),
            source_detail=f"open_prices:{item.get('id')}",
        )
        imported += 1
    conn.commit()
    return imported
