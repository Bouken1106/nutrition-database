from __future__ import annotations

import logging
import sqlite3

import requests

from src.db.repository import replace_food_nutrients, upsert_food
from src.normalize.names import build_food_id, build_source_key
from src.normalize.units import convert_unit, normalize_unit, parse_quantity_text

LOGGER = logging.getLogger(__name__)
USER_AGENT = "nutrition-database/1.0 (local@example.invalid)"
SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
SEARCH_A_LICIOUS_URL = "https://search.openfoodfacts.org/search"
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
SUPPORTED_NUTRIENTS = {
    "energy_kcal": ("energy-kcal_100g", "kcal"),
    "protein_g": ("proteins_100g", "g"),
    "fat_g": ("fat_100g", "g"),
    "carb_g": ("carbohydrates_100g", "g"),
    "fiber_g": ("fiber_100g", "g"),
    "calcium_mg": ("calcium_100g", "mg"),
    "iron_mg": ("iron_100g", "mg"),
    "vitamin_a_ug": ("vitamin-a_100g", "ug"),
    "vitamin_b1_mg": ("vitamin-b1_100g", "mg"),
    "vitamin_b2_mg": ("vitamin-b2_100g", "mg"),
    "vitamin_c_mg": ("vitamin-c_100g", "mg"),
}


def sync_products(conn: sqlite3.Connection, query: str, session: requests.Session | None = None) -> int:
    client = session or requests.Session()
    products = search_products(query, client)
    imported = 0
    for product in products:
        if upsert_off_product(conn, product):
            imported += 1
    conn.commit()
    return imported


def search_products(query: str, client: requests.Session) -> list[dict[str, object]]:
    search_a_licious_error: requests.RequestException | None = None
    try:
        products = search_products_search_a_licious(query, client)
        if products:
            return products
    except requests.RequestException as exc:
        search_a_licious_error = exc
        LOGGER.debug("Open Food Facts Search-a-licious search failed: %s", exc)

    try:
        return search_products_legacy(query, client)
    except requests.RequestException as exc:
        if search_a_licious_error is not None:
            raise RuntimeError(
                "Open Food Facts search failed for both Search-a-licious and legacy endpoints"
            ) from exc
        raise


def search_products_search_a_licious(query: str, client: requests.Session) -> list[dict[str, object]]:
    response = client.get(
        SEARCH_A_LICIOUS_URL,
        params={"q": query, "size": 25},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    products = payload.get("hits", [])
    if not isinstance(products, list):
        raise RuntimeError("Open Food Facts search returned an unexpected payload")
    return products


def search_products_legacy(query: str, client: requests.Session) -> list[dict[str, object]]:
    response = client.get(
        SEARCH_URL,
        params={
            "search_terms": query,
            "search_simple": 1,
            "action": "process",
            "json": 1,
            "page_size": 25,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    products = payload.get("products", [])
    if not isinstance(products, list):
        raise RuntimeError("Open Food Facts search returned an unexpected payload")
    return products


def sync_product_by_code(
    conn: sqlite3.Connection,
    product_code: str,
    session: requests.Session | None = None,
) -> bool:
    client = session or requests.Session()
    response = client.get(
        PRODUCT_URL.format(code=product_code),
        params={"fields": "code,product_name,product_name_ja,product_name_en,nutriments,quantity"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 404:
            raise ValueError(f"product code not found in Open Food Facts: {product_code}") from exc
        raise
    payload = response.json()
    product = payload.get("product")
    if not product:
        raise ValueError(f"product code not found in Open Food Facts: {product_code}")
    inserted = upsert_off_product(conn, product)
    conn.commit()
    return inserted


def upsert_off_product(conn: sqlite3.Connection, product: dict[str, object]) -> bool:
    code = str(product.get("code") or "").strip()
    if not code:
        return False
    name = (
        product.get("product_name_ja")
        or product.get("product_name_en")
        or product.get("product_name")
        or f"OFF {code}"
    )
    source_key = build_source_key(str(name), code)
    food_id = build_food_id("off", source_key)
    quantity_value, quantity_unit = infer_default_unit(product)
    default_unit = "g"
    if quantity_unit in {"ml", "l"}:
        default_unit = "ml"
    elif quantity_unit in {"piece"}:
        default_unit = "piece"
    upsert_food(
        conn,
        food_id=food_id,
        name=str(name).strip(),
        source_type="off",
        source_key=code,
        canonical_name=None,
        default_unit=default_unit,
        edible_ratio=1.0,
    )
    nutrient_amounts = extract_supported_nutrients(product.get("nutriments") or {})
    replace_food_nutrients(conn, food_id, nutrient_amounts)
    return True


def infer_default_unit(product: dict[str, object]) -> tuple[float | None, str | None]:
    quantity = product.get("quantity")
    parsed = parse_quantity_text(quantity)
    if parsed is not None:
        return parsed
    return None, normalize_unit(None)


def extract_supported_nutrients(nutriments: dict[str, object]) -> dict[str, float]:
    nutrient_amounts: dict[str, float] = {}
    for nutrient_id, (value_key, expected_unit) in SUPPORTED_NUTRIENTS.items():
        value = nutriments.get(value_key)
        if value is None:
            continue
        unit_key = value_key.replace("_100g", "_unit")
        converted = convert_unit(float(value), nutriments.get(unit_key, expected_unit), expected_unit)
        if converted is None:
            try:
                converted = float(value)
            except (TypeError, ValueError):
                continue
        nutrient_amounts[nutrient_id] = converted
    return nutrient_amounts
