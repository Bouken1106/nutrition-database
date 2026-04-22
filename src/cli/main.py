from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.db.connection import DEFAULT_DB_PATH, ensure_database, get_connection
from src.export.csv_export import export_all_csv, export_unmatched_csv
from src.gui import launch_gui
from src.ingest.estat import import_estat
from src.ingest.mext import import_mext
from src.ingest.open_food_facts import sync_products
from src.ingest.open_prices import sync_prices_for_product
from src.optimize.solver import solve_diet_to_file
from src.normalize.mapping import auto_map_foods, manual_map_foods


class JapaneseArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self._positionals.title = "コマンド"
        self._optionals.title = "オプション"
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="ヘルプを表示して終了する")

    def format_help(self) -> str:
        help_text = super().format_help()
        return (
            help_text.replace("usage:", "使い方:")
            .replace("options:", "オプション:")
            .replace("positional arguments:", "コマンド:")
        )


def build_parser() -> argparse.ArgumentParser:
    parser = JapaneseArgumentParser(description="栄養条件を満たす最安の食事を求めるツール")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite データベースのパス")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JapaneseArgumentParser)

    init_parser = subparsers.add_parser("init-db", help="SQLite データベースを初期化する")
    init_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    ingest_mext_parser = subparsers.add_parser("ingest-mext", help="MEXT 食品成分データを取り込む")
    ingest_mext_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ingest_mext_parser.add_argument("--input", required=True, help="MEXT Excel ファイルのパス")

    ingest_estat_parser = subparsers.add_parser("ingest-estat", help="e-Stat 小売価格データを取り込む")
    ingest_estat_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ingest_estat_parser.add_argument("--input", required=True, help="e-Stat CSV または Excel ファイルのパス")

    off_parser = subparsers.add_parser("sync-off-products", help="Open Food Facts の商品を検索して取り込む")
    off_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    off_parser.add_argument("--query", required=True, help="検索キーワード")

    prices_parser = subparsers.add_parser("sync-open-prices", help="Open Prices の価格情報を取り込む")
    prices_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    prices_parser.add_argument("--product-code", required=True, help="商品のバーコード")

    mapping_parser = subparsers.add_parser("map-foods", help="e-Stat 食品を MEXT 食品に対応付ける")
    mapping_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    mapping_group = mapping_parser.add_mutually_exclusive_group(required=True)
    mapping_group.add_argument("--auto", action="store_true", help="保守的な自動マッピングを実行する")
    mapping_group.add_argument("--manual", help="手動マッピング用 CSV のパス")

    solve_parser = subparsers.add_parser("solve-diet", help="最適化を実行して日次の食事案を求める")
    solve_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    solve_parser.add_argument("--targets", required=True, help="ターゲット JSON のパス")
    solve_parser.add_argument("--output", required=True, help="出力先 JSON のパス")

    export_parser = subparsers.add_parser("export-csv", help="正規化済みテーブルを CSV で出力する")
    export_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    export_parser.add_argument("--output-dir", required=True, help="CSV の出力先ディレクトリ")

    unmatched_parser = subparsers.add_parser("export-unmatched", help="未対応付けデータを CSV で出力する")
    unmatched_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    unmatched_parser.add_argument("--output", required=True, help="CSV の出力先パス")

    gui_parser = subparsers.add_parser("launch-gui", help="ローカル GUI を起動する")
    gui_parser.add_argument("--db", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        db_path = ensure_database(args.db)
        if args.command == "init-db":
            logging.info("データベースを初期化しました: %s", db_path)
            return 0
        if args.command == "launch-gui":
            return launch_gui(db_path)
        with get_connection(db_path) as conn:
            if args.command == "ingest-mext":
                imported = import_mext(conn, args.input)
                logging.info("MEXT データを %s 件取り込みました", imported)
                return 0
            if args.command == "ingest-estat":
                imported = import_estat(conn, args.input)
                logging.info("e-Stat データを %s 件取り込みました", imported)
                return 0
            if args.command == "sync-off-products":
                imported = sync_products(conn, args.query)
                logging.info("Open Food Facts の商品を %s 件取り込みました", imported)
                return 0
            if args.command == "sync-open-prices":
                imported = sync_prices_for_product(conn, args.product_code)
                logging.info("Open Prices の価格情報を %s 件取り込みました", imported)
                return 0
            if args.command == "map-foods":
                if args.auto:
                    imported = auto_map_foods(conn)
                    logging.info("自動マッピングを %s 件作成しました", imported)
                else:
                    imported = manual_map_foods(conn, args.manual)
                    logging.info("手動マッピングを %s 件作成しました", imported)
                return 0
            if args.command == "solve-diet":
                result = solve_diet_to_file(conn, args.targets, args.output)
                logging.info("最適化結果 (%s) を %s に出力しました", result["status"], args.output)
                return 0
            if args.command == "export-csv":
                outputs = export_all_csv(conn, args.output_dir)
                for name, path in outputs.items():
                    logging.info("%s を出力しました: %s", name, path)
                return 0
            if args.command == "export-unmatched":
                output = export_unmatched_csv(conn, args.output)
                logging.info("未対応付け一覧を出力しました: %s", output)
                return 0
    except Exception as exc:
        logging.error(str(exc))
        return 1
    parser.error(f"未対応のコマンドです: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
