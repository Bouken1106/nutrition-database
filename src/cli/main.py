from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.db.connection import DEFAULT_DB_PATH, ensure_database, get_connection
from src.export.csv_export import export_all_csv, export_unmatched_csv
from src.ingest.estat import import_estat
from src.ingest.mext import import_mext
from src.ingest.open_food_facts import sync_products
from src.ingest.open_prices import sync_prices_for_product
from src.optimize.solver import solve_diet_to_file
from src.normalize.mapping import auto_map_foods, manual_map_foods


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cheapest nutrition-constrained diet optimizer")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Initialize the SQLite schema")
    init_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)

    ingest_mext_parser = subparsers.add_parser("ingest-mext", help="Import MEXT food composition data")
    ingest_mext_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    ingest_mext_parser.add_argument("--input", required=True, help="Path to the MEXT Excel file")

    ingest_estat_parser = subparsers.add_parser("ingest-estat", help="Import e-Stat retail price data")
    ingest_estat_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    ingest_estat_parser.add_argument("--input", required=True, help="Path to the e-Stat CSV or Excel file")

    off_parser = subparsers.add_parser("sync-off-products", help="Fetch Open Food Facts products by text query")
    off_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    off_parser.add_argument("--query", required=True, help="Search text")

    prices_parser = subparsers.add_parser("sync-open-prices", help="Fetch Open Prices records for a barcode")
    prices_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    prices_parser.add_argument("--product-code", required=True, help="Product barcode")

    mapping_parser = subparsers.add_parser("map-foods", help="Map e-Stat foods to MEXT foods")
    mapping_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    mapping_group = mapping_parser.add_mutually_exclusive_group(required=True)
    mapping_group.add_argument("--auto", action="store_true", help="Run conservative auto mapping")
    mapping_group.add_argument("--manual", help="CSV override path for manual mapping")

    solve_parser = subparsers.add_parser("solve-diet", help="Solve cheapest daily diet")
    solve_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    solve_parser.add_argument("--targets", required=True, help="Targets JSON path")
    solve_parser.add_argument("--output", required=True, help="Output JSON path")

    export_parser = subparsers.add_parser("export-csv", help="Export normalized tables to CSV")
    export_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    export_parser.add_argument("--output-dir", required=True, help="CSV output directory")

    unmatched_parser = subparsers.add_parser("export-unmatched", help="Export unmatched mapping rows to CSV")
    unmatched_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help=argparse.SUPPRESS)
    unmatched_parser.add_argument("--output", required=True, help="CSV output path")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        db_path = ensure_database(args.db)
        if args.command == "init-db":
            logging.info("initialized database at %s", db_path)
            return 0
        with get_connection(db_path) as conn:
            if args.command == "ingest-mext":
                imported = import_mext(conn, args.input)
                logging.info("imported %s MEXT rows", imported)
                return 0
            if args.command == "ingest-estat":
                imported = import_estat(conn, args.input)
                logging.info("imported %s e-Stat rows", imported)
                return 0
            if args.command == "sync-off-products":
                imported = sync_products(conn, args.query)
                logging.info("imported %s Open Food Facts products", imported)
                return 0
            if args.command == "sync-open-prices":
                imported = sync_prices_for_product(conn, args.product_code)
                logging.info("imported %s Open Prices records", imported)
                return 0
            if args.command == "map-foods":
                if args.auto:
                    imported = auto_map_foods(conn)
                    logging.info("created %s automatic mappings", imported)
                else:
                    imported = manual_map_foods(conn, args.manual)
                    logging.info("created %s manual mappings", imported)
                return 0
            if args.command == "solve-diet":
                result = solve_diet_to_file(conn, args.targets, args.output)
                logging.info("wrote %s result to %s", result["status"], args.output)
                return 0
            if args.command == "export-csv":
                outputs = export_all_csv(conn, args.output_dir)
                for name, path in outputs.items():
                    logging.info("%s -> %s", name, path)
                return 0
            if args.command == "export-unmatched":
                output = export_unmatched_csv(conn, args.output)
                logging.info("unmatched mappings -> %s", output)
                return 0
    except Exception as exc:
        logging.error(str(exc))
        return 1
    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
