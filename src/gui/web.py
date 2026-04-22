from __future__ import annotations

import html
import json
import logging
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from src.db.connection import DEFAULT_DB_PATH, ensure_database, get_connection
from src.export.csv_export import export_all_csv, export_unmatched_csv
from src.ingest.estat import import_estat
from src.ingest.mext import import_mext
from src.ingest.open_food_facts import sync_products
from src.ingest.open_prices import sync_prices_for_product
from src.gui.solution_summary import format_value, is_solution_result, status_label, target_range_text
from src.normalize.mapping import auto_map_foods, manual_map_foods
from src.optimize.solver import solve_diet_to_file

LOGGER = logging.getLogger(__name__)


def launch_browser_gui(db_path: str | Path = DEFAULT_DB_PATH) -> int:
    app = BrowserGuiServer(db_path)
    return app.serve()


class BrowserGuiServer:
    def __init__(self, db_path: str | Path) -> None:
        self.default_db_path = str(db_path)
        self.status_text = "待機中"
        self.result_text = ""
        self.solution_result: dict[str, object] | None = None
        self.log_lines: list[str] = []
        self.form_values = {
            "db_path": self.default_db_path,
            "mext_input_path": "data/raw/mext.xlsx",
            "estat_input_path": "data/raw/estat.csv",
            "query": "オートミール",
            "product_code": "",
            "manual_input_path": "data/raw/manual_mapping.csv",
            "targets_path": "data/raw/targets.json",
            "solution_output_path": "outputs/solution.json",
            "csv_output_dir": "outputs/csv",
            "unmatched_output_path": "outputs/unmatched.csv",
        }
        self._state_lock = threading.Lock()

    def serve(self) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_factory())
        url = f"http://127.0.0.1:{server.server_port}/"
        LOGGER.info("ブラウザ GUI を起動しました: %s", url)
        LOGGER.info("停止するには Ctrl+C を押してください")
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("ブラウザ GUI を停止しました")
        finally:
            server.server_close()
        return 0

    def _handler_factory(self) -> type[BaseHTTPRequestHandler]:
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/":
                    self._send_not_found()
                    return
                body = parent._render_index()
                encoded = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/action":
                    self._handle_form_post()
                    return
                if self.path != "/api/action":
                    self._send_not_found()
                    return
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                try:
                    payload = json.loads(raw.decode("utf-8") or "{}")
                    result = parent._perform_action(payload)
                    response = {"ok": True, **result}
                    status = HTTPStatus.OK
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                    status = HTTPStatus.BAD_REQUEST
                encoded = json.dumps(response, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, fmt: str, *args: object) -> None:
                LOGGER.debug("browser-gui: " + fmt, *args)

            def _handle_form_post(self) -> None:
                content_length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_length)
                payload = {
                    key: values[0] if values else ""
                    for key, values in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()
                }
                action = str(payload.get("action") or "").strip()
                label = parent._action_label(action)
                parent._update_form_values(payload)
                try:
                    result = parent._perform_action(parent._normalize_form_payload(payload))
                    parent._record_success(
                        label,
                        str(result.get("message") or f"{label}が完了しました"),
                        result.get("result_text"),
                        result.get("solution_result"),
                    )
                except Exception as exc:
                    parent._record_error(label, str(exc))
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/")
                self.end_headers()

            def _send_not_found(self) -> None:
                body = json.dumps({"ok": False, "error": "ページが見つかりません"}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def _action_label(self, action: str) -> str:
        return {
            "init_db": "DB 初期化",
            "import_mext": "MEXT 取り込み",
            "import_estat": "e-Stat 取り込み",
            "sync_off_products": "OFF 商品同期",
            "sync_open_prices": "Open Prices 同期",
            "auto_mapping": "自動マッピング",
            "manual_mapping": "手動マッピング",
            "solve_diet": "最適化",
            "export_csv": "CSV 出力",
            "export_unmatched": "未対応付け一覧出力",
        }.get(action, "処理")

    def _record_success(
        self,
        label: str,
        message: str,
        result_text: object | None = None,
        solution_result: object | None = None,
    ) -> None:
        with self._state_lock:
            self.status_text = message
            self._append_log(f"{label}: {message}")
            if result_text is not None:
                self.result_text = str(result_text)
            if is_solution_result(solution_result):
                self.solution_result = solution_result

    def _record_error(self, label: str, error_text: str) -> None:
        with self._state_lock:
            self.status_text = f"{label}に失敗しました"
            self._append_log(f"{label}: 失敗 / {error_text}")

    def _update_form_values(self, payload: dict[str, str]) -> None:
        with self._state_lock:
            for key in self.form_values:
                if key in payload:
                    self.form_values[key] = payload[key]

    def _normalize_form_payload(self, payload: dict[str, str]) -> dict[str, object]:
        normalized: dict[str, object] = {
            "action": payload.get("action", ""),
            "db_path": payload.get("db_path", self.form_values["db_path"]),
            "query": payload.get("query", self.form_values["query"]),
            "product_code": payload.get("product_code", self.form_values["product_code"]),
            "targets_path": payload.get("targets_path", self.form_values["targets_path"]),
        }
        action = str(payload.get("action") or "").strip()
        if action == "import_mext":
            normalized["input_path"] = payload.get("mext_input_path", self.form_values["mext_input_path"])
        elif action == "import_estat":
            normalized["input_path"] = payload.get("estat_input_path", self.form_values["estat_input_path"])
        elif action == "manual_mapping":
            normalized["input_path"] = payload.get("manual_input_path", self.form_values["manual_input_path"])
        elif action == "solve_diet":
            normalized["output_path"] = payload.get("solution_output_path", self.form_values["solution_output_path"])
        elif action == "export_csv":
            normalized["output_dir"] = payload.get("csv_output_dir", self.form_values["csv_output_dir"])
        elif action == "export_unmatched":
            normalized["output_path"] = payload.get("unmatched_output_path", self.form_values["unmatched_output_path"])
        return normalized

    def _append_log(self, message: str) -> None:
        self.log_lines.append(message)
        if len(self.log_lines) > 100:
            self.log_lines = self.log_lines[-100:]

    def _perform_action(self, payload: dict[str, object]) -> dict[str, object]:
        action = self._require_text(payload, "action")
        db_path = Path(self._require_text(payload, "db_path"))
        db_file = ensure_database(db_path)

        if action == "init_db":
            return {"message": f"データベースを初期化しました: {db_file}"}
        if action == "import_mext":
            input_path = Path(self._require_text(payload, "input_path"))
            with get_connection(db_file) as conn:
                imported = import_mext(conn, input_path)
            return {"message": f"MEXT データを {imported} 件取り込みました: {input_path}"}
        if action == "import_estat":
            input_path = Path(self._require_text(payload, "input_path"))
            with get_connection(db_file) as conn:
                imported = import_estat(conn, input_path)
            return {"message": f"e-Stat データを {imported} 件取り込みました: {input_path}"}
        if action == "sync_off_products":
            query = self._require_text(payload, "query")
            with get_connection(db_file) as conn:
                imported = sync_products(conn, query)
            return {"message": f"Open Food Facts の商品を {imported} 件取り込みました: 検索語={query}"}
        if action == "sync_open_prices":
            product_code = self._require_text(payload, "product_code")
            with get_connection(db_file) as conn:
                imported = sync_prices_for_product(conn, product_code)
            return {"message": f"Open Prices の価格情報を {imported} 件取り込みました: バーコード={product_code}"}
        if action == "auto_mapping":
            with get_connection(db_file) as conn:
                imported = auto_map_foods(conn)
            return {"message": f"自動マッピングを {imported} 件作成しました"}
        if action == "manual_mapping":
            input_path = Path(self._require_text(payload, "input_path"))
            with get_connection(db_file) as conn:
                imported = manual_map_foods(conn, input_path)
            return {"message": f"手動マッピングを {imported} 件反映しました: {input_path}"}
        if action == "solve_diet":
            targets_path = Path(self._require_text(payload, "targets_path"))
            output_path = Path(self._require_text(payload, "output_path"))
            with get_connection(db_file) as conn:
                result = solve_diet_to_file(conn, targets_path, output_path)
            return {
                "message": f"最適化結果 ({result['status']}) を出力しました: {output_path}",
                "result_text": json.dumps(result, ensure_ascii=False, indent=2),
                "solution_result": result,
            }
        if action == "export_csv":
            output_dir = Path(self._require_text(payload, "output_dir"))
            with get_connection(db_file) as conn:
                outputs = export_all_csv(conn, output_dir)
            return {
                "message": f"正規化済み CSV を出力しました: {output_dir}",
                "result_text": json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2),
            }
        if action == "export_unmatched":
            output_path = Path(self._require_text(payload, "output_path"))
            with get_connection(db_file) as conn:
                exported = export_unmatched_csv(conn, output_path)
            return {"message": f"未対応付け一覧を出力しました: {exported}"}
        raise ValueError(f"未対応の操作です: {action}")

    def _require_text(self, payload: dict[str, object], key: str) -> str:
        value = str(payload.get(key) or "").strip()
        if not value:
            labels = {
                "action": "操作名",
                "db_path": "SQLite データベースのパス",
                "input_path": "入力ファイルのパス",
                "query": "検索語",
                "product_code": "商品のバーコード",
                "targets_path": "ターゲット JSON のパス",
                "output_path": "出力先ファイルのパス",
                "output_dir": "出力先ディレクトリのパス",
            }
            raise ValueError(f"{labels.get(key, key)}を入力してください")
        return value

    def _render_index(self) -> str:
        with self._state_lock:
            status_text = self.status_text
            result_text = self.result_text
            solution_result = self.solution_result
            log_text = "\n".join(self.log_lines)
            form_values = dict(self.form_values)
        db_path = html.escape(form_values["db_path"])
        mext_input_path = html.escape(form_values["mext_input_path"])
        estat_input_path = html.escape(form_values["estat_input_path"])
        query = html.escape(form_values["query"])
        product_code = html.escape(form_values["product_code"])
        manual_input_path = html.escape(form_values["manual_input_path"])
        targets_path = html.escape(form_values["targets_path"])
        solution_output_path = html.escape(form_values["solution_output_path"])
        csv_output_dir = html.escape(form_values["csv_output_dir"])
        unmatched_output_path = html.escape(form_values["unmatched_output_path"])
        status_text = html.escape(status_text)
        result_text = html.escape(result_text)
        log_text = html.escape(log_text)
        solution_summary = self._render_solution_summary_html(solution_result)
        return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>nutrition-database 操作画面</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffaf2;
      --line: #d8cbb4;
      --ink: #2b241b;
      --muted: #6f634f;
      --accent: #1d6b57;
      --accent-2: #d97a2b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Hiragino Sans", "Yu Gothic", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(217,122,43,0.18), transparent 30%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }}
    main {{
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 2rem;
      letter-spacing: 0.02em;
    }}
    p {{
      margin: 0 0 20px;
      color: var(--muted);
    }}
    .card {{
      background: rgba(255, 250, 242, 0.94);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 14px 36px rgba(55, 36, 10, 0.08);
    }}
    .grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    }}
    .wide {{
      grid-column: 1 / -1;
    }}
    .field-grid {{
      display: grid;
      gap: 12px;
    }}
    label {{
      display: block;
      font-size: 0.92rem;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    input, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px 14px;
      font: inherit;
      background: #fffdf9;
      color: var(--ink);
    }}
    textarea {{
      min-height: 180px;
      resize: vertical;
    }}
    button {{
      border: none;
      border-radius: 999px;
      padding: 11px 16px;
      font: inherit;
      font-weight: 700;
      color: #fff;
      background: linear-gradient(135deg, var(--accent), #0f4d3f);
      cursor: pointer;
    }}
    button.alt {{
      background: linear-gradient(135deg, var(--accent-2), #b55a13);
    }}
    button:disabled {{
      opacity: 0.6;
      cursor: progress;
    }}
    .actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 10px;
    }}
    .status {{
      margin: 14px 0 18px;
      font-weight: 700;
    }}
    .hint {{
      font-size: 0.88rem;
      color: var(--muted);
      margin-top: 8px;
    }}
    .metrics {{
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      margin-bottom: 14px;
    }}
    .metric {{
      padding: 14px;
      border-radius: 14px;
      background: rgba(29, 107, 87, 0.08);
      border: 1px solid rgba(29, 107, 87, 0.16);
    }}
    .metric-label {{
      font-size: 0.84rem;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .metric-value {{
      font-size: 1.1rem;
      font-weight: 700;
    }}
    .summary-section + .summary-section {{
      margin-top: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-weight: 700;
    }}
    ul {{
      margin: 8px 0 0;
      padding-left: 18px;
    }}
    .empty {{
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      main {{ padding: 16px; }}
      h1 {{ font-size: 1.65rem; }}
      table, thead, tbody, tr, th, td {{
        display: block;
      }}
      thead {{
        display: none;
      }}
      td {{
        padding: 6px 0;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>nutrition-database 操作画面</h1>
    <p>ローカルで動く GUI です。入力ファイルと出力先はこのマシン上のパスを指定してください。ボタンを押すとページが再読み込みされます。</p>
    <div class="status">{status_text}</div>
    <form method="post" action="/action">
    <section class="grid">
      <div class="card wide">
        <div class="field-grid">
          <div>
            <label for="dbPath">SQLite データベース</label>
            <input id="dbPath" name="db_path" value="{db_path}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="init_db">DB を初期化</button>
        </div>
      </div>

      <div class="card">
        <h2>取り込み</h2>
        <div class="field-grid">
          <div>
            <label for="mextInput">MEXT ファイル</label>
            <input id="mextInput" name="mext_input_path" value="{mext_input_path}">
          </div>
          <div>
            <label for="estatInput">e-Stat ファイル</label>
            <input id="estatInput" name="estat_input_path" value="{estat_input_path}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="import_mext">MEXT を取り込む</button>
          <button type="submit" name="action" value="import_estat">e-Stat を取り込む</button>
        </div>
      </div>

      <div class="card">
        <h2>同期</h2>
        <div class="field-grid">
          <div>
            <label for="offQuery">Open Food Facts の検索語</label>
            <input id="offQuery" name="query" value="{query}">
          </div>
          <div>
            <label for="productCode">商品のバーコード</label>
            <input id="productCode" name="product_code" value="{product_code}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="sync_off_products">OFF 商品を同期</button>
          <button type="submit" name="action" value="sync_open_prices">Open Prices を同期</button>
        </div>
      </div>

      <div class="card">
        <h2>マッピング</h2>
        <div class="field-grid">
          <div>
            <label for="manualMapping">手動マッピング CSV</label>
            <input id="manualMapping" name="manual_input_path" value="{manual_input_path}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="auto_mapping">自動マッピングを実行</button>
          <button type="submit" name="action" value="manual_mapping">手動マッピングを反映</button>
        </div>
        <div class="hint">自動マッピングでは、完全一致と保守的な正規化名一致だけを使います。</div>
      </div>

      <div class="card">
        <h2>最適化</h2>
        <div class="field-grid">
          <div>
            <label for="targetsPath">ターゲット JSON</label>
            <input id="targetsPath" name="targets_path" value="{targets_path}">
          </div>
          <div>
            <label for="solutionOutput">結果 JSON</label>
            <input id="solutionOutput" name="solution_output_path" value="{solution_output_path}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="solve_diet" class="alt">最適化を実行</button>
        </div>
      </div>

      <div class="card">
        <h2>出力</h2>
        <div class="field-grid">
          <div>
            <label for="csvOutputDir">CSV 出力先ディレクトリ</label>
            <input id="csvOutputDir" name="csv_output_dir" value="{csv_output_dir}">
          </div>
          <div>
            <label for="unmatchedOutput">未対応付け CSV</label>
            <input id="unmatchedOutput" name="unmatched_output_path" value="{unmatched_output_path}">
          </div>
        </div>
        <div class="actions">
          <button type="submit" name="action" value="export_csv">CSV を出力</button>
          <button type="submit" name="action" value="export_unmatched">未対応付け一覧を出力</button>
        </div>
      </div>

      <div class="card wide">
        <h2>最適化結果サマリー</h2>
        {solution_summary}
      </div>

      <div class="card">
        <h2>結果 JSON</h2>
        <textarea id="resultText" spellcheck="false" readonly>{result_text}</textarea>
      </div>

      <div class="card">
        <h2>実行ログ</h2>
        <textarea id="logText" spellcheck="false" readonly>{log_text}</textarea>
      </div>
    </section>
  </form>
  </main>
</body>
</html>"""

    def _render_solution_summary_html(self, result: dict[str, object] | None) -> str:
        if not is_solution_result(result):
            return '<p class="empty">まだ最適化結果はありません。まず「最適化を実行」を押してください。</p>'

        assert result is not None
        metrics = [
            ("状態", f"{status_label(result.get('status'))} ({format_value(result.get('status'))})"),
            ("合計コスト", f"{format_value(result.get('total_cost_yen'))} 円"),
            ("除外食品数", f"{format_value(result.get('excluded_foods_count'))} 件"),
        ]
        metric_html = "".join(
            "<div class=\"metric\">"
            f"<div class=\"metric-label\">{html.escape(label)}</div>"
            f"<div class=\"metric-value\">{html.escape(value)}</div>"
            "</div>"
            for label, value in metrics
        )

        notes = result.get("notes")
        notes_html = '<p class="empty">特記事項はありません。</p>'
        if isinstance(notes, list) and notes:
            notes_items = "".join(f"<li>{html.escape(format_value(note))}</li>" for note in notes)
            notes_html = f"<ul>{notes_items}</ul>"

        foods = result.get("foods")
        foods_html = '<p class="empty">選ばれた食品はありません。</p>'
        if isinstance(foods, list) and foods:
            food_rows = []
            for food in foods:
                if not isinstance(food, dict):
                    continue
                food_rows.append(
                    "<tr>"
                    f"<td>{html.escape(format_value(food.get('food_id')))}</td>"
                    f"<td>{html.escape(format_value(food.get('name')))}</td>"
                    f"<td>{html.escape(format_value(food.get('amount_g')))} g</td>"
                    f"<td>{html.escape(format_value(food.get('cost_yen')))} 円</td>"
                    "</tr>"
                )
            if food_rows:
                foods_html = (
                    "<table>"
                    "<thead><tr><th>食品ID</th><th>食品名</th><th>量</th><th>費用</th></tr></thead>"
                    f"<tbody>{''.join(food_rows)}</tbody>"
                    "</table>"
                )

        nutrients = result.get("nutrients")
        nutrients_html = '<p class="empty">栄養素の結果はありません。</p>'
        if isinstance(nutrients, list) and nutrients:
            nutrient_rows = []
            for nutrient in nutrients:
                if not isinstance(nutrient, dict):
                    continue
                nutrient_rows.append(
                    "<tr>"
                    f"<td>{html.escape(format_value(nutrient.get('nutrient_id')))}</td>"
                    f"<td>{html.escape(format_value(nutrient.get('actual')))}</td>"
                    f"<td>{html.escape(target_range_text(nutrient.get('target_min'), nutrient.get('target_max')))}</td>"
                    "</tr>"
                )
            if nutrient_rows:
                nutrients_html = (
                    "<table>"
                    "<thead><tr><th>栄養素</th><th>実績</th><th>目標</th></tr></thead>"
                    f"<tbody>{''.join(nutrient_rows)}</tbody>"
                    "</table>"
                )

        return (
            f"<div class=\"metrics\">{metric_html}</div>"
            "<div class=\"summary-section\"><h3>選ばれた食品</h3>"
            f"{foods_html}</div>"
            "<div class=\"summary-section\"><h3>栄養素の達成状況</h3>"
            f"{nutrients_html}</div>"
            "<div class=\"summary-section\"><h3>注意事項</h3>"
            f"{notes_html}</div>"
        )
