from __future__ import annotations

import json
import logging
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.db.connection import DEFAULT_DB_PATH, ensure_database, get_connection
from src.export.csv_export import export_all_csv, export_unmatched_csv
from src.ingest.estat import import_estat
from src.ingest.mext import import_mext
from src.ingest.open_food_facts import sync_products
from src.ingest.open_prices import sync_prices_for_product
from src.normalize.mapping import auto_map_foods, manual_map_foods
from src.optimize.solver import solve_diet_to_file

LOGGER = logging.getLogger(__name__)


def launch_browser_gui(db_path: str | Path = DEFAULT_DB_PATH) -> int:
    app = BrowserGuiServer(db_path)
    return app.serve()


class BrowserGuiServer:
    def __init__(self, db_path: str | Path) -> None:
        self.default_db_path = str(db_path)

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
                    self.send_error(HTTPStatus.NOT_FOUND, "ページが見つかりません")
                    return
                body = parent._render_index()
                encoded = body.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/action":
                    self.send_error(HTTPStatus.NOT_FOUND, "ページが見つかりません")
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

        return Handler

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
        db_path = json.dumps(self.default_db_path)
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
    @media (max-width: 720px) {{
      main {{ padding: 16px; }}
      h1 {{ font-size: 1.65rem; }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>nutrition-database 操作画面</h1>
    <p>ローカルで動く GUI です。入力ファイルと出力先はこのマシン上のパスを指定してください。</p>
    <div class="status" id="status">待機中</div>
    <section class="grid">
      <div class="card wide">
        <div class="field-grid">
          <div>
            <label for="dbPath">SQLite データベース</label>
            <input id="dbPath" value="">
          </div>
        </div>
        <div class="actions">
          <button type="button" onclick="runAction('init_db', 'DB 初期化', {{ db_path: value('dbPath') }})">DB を初期化</button>
        </div>
      </div>

      <div class="card">
        <h2>取り込み</h2>
        <div class="field-grid">
          <div>
            <label for="mextInput">MEXT ファイル</label>
            <input id="mextInput" value="data/raw/mext.xlsx">
          </div>
          <div>
            <label for="estatInput">e-Stat ファイル</label>
            <input id="estatInput" value="data/raw/estat.csv">
          </div>
        </div>
        <div class="actions">
          <button type="button" onclick="runAction('import_mext', 'MEXT 取り込み', {{ db_path: value('dbPath'), input_path: value('mextInput') }})">MEXT を取り込む</button>
          <button type="button" onclick="runAction('import_estat', 'e-Stat 取り込み', {{ db_path: value('dbPath'), input_path: value('estatInput') }})">e-Stat を取り込む</button>
        </div>
      </div>

      <div class="card">
        <h2>同期</h2>
        <div class="field-grid">
          <div>
            <label for="offQuery">Open Food Facts の検索語</label>
            <input id="offQuery" value="オートミール">
          </div>
          <div>
            <label for="productCode">商品のバーコード</label>
            <input id="productCode" value="">
          </div>
        </div>
        <div class="actions">
          <button type="button" onclick="runAction('sync_off_products', 'OFF 商品同期', {{ db_path: value('dbPath'), query: value('offQuery') }})">OFF 商品を同期</button>
          <button type="button" onclick="runAction('sync_open_prices', 'Open Prices 同期', {{ db_path: value('dbPath'), product_code: value('productCode') }})">Open Prices を同期</button>
        </div>
      </div>

      <div class="card">
        <h2>マッピング</h2>
        <div class="field-grid">
          <div>
            <label for="manualMapping">手動マッピング CSV</label>
            <input id="manualMapping" value="data/raw/manual_mapping.csv">
          </div>
        </div>
        <div class="actions">
          <button type="button" onclick="runAction('auto_mapping', '自動マッピング', {{ db_path: value('dbPath') }})">自動マッピングを実行</button>
          <button type="button" onclick="runAction('manual_mapping', '手動マッピング', {{ db_path: value('dbPath'), input_path: value('manualMapping') }})">手動マッピングを反映</button>
        </div>
        <div class="hint">自動マッピングでは、完全一致と保守的な正規化名一致だけを使います。</div>
      </div>

      <div class="card">
        <h2>最適化</h2>
        <div class="field-grid">
          <div>
            <label for="targetsPath">ターゲット JSON</label>
            <input id="targetsPath" value="data/raw/targets.json">
          </div>
          <div>
            <label for="solutionOutput">結果 JSON</label>
            <input id="solutionOutput" value="outputs/solution.json">
          </div>
        </div>
        <div class="actions">
          <button type="button" class="alt" onclick="runAction('solve_diet', '最適化', {{ db_path: value('dbPath'), targets_path: value('targetsPath'), output_path: value('solutionOutput') }})">最適化を実行</button>
        </div>
      </div>

      <div class="card">
        <h2>出力</h2>
        <div class="field-grid">
          <div>
            <label for="csvOutputDir">CSV 出力先ディレクトリ</label>
            <input id="csvOutputDir" value="outputs/csv">
          </div>
          <div>
            <label for="unmatchedOutput">未対応付け CSV</label>
            <input id="unmatchedOutput" value="outputs/unmatched.csv">
          </div>
        </div>
        <div class="actions">
          <button type="button" onclick="runAction('export_csv', 'CSV 出力', {{ db_path: value('dbPath'), output_dir: value('csvOutputDir') }})">CSV を出力</button>
          <button type="button" onclick="runAction('export_unmatched', '未対応付け一覧出力', {{ db_path: value('dbPath'), output_path: value('unmatchedOutput') }})">未対応付け一覧を出力</button>
        </div>
      </div>

      <div class="card">
        <h2>結果プレビュー</h2>
        <textarea id="resultText" spellcheck="false"></textarea>
      </div>

      <div class="card">
        <h2>実行ログ</h2>
        <textarea id="logText" spellcheck="false"></textarea>
      </div>
    </section>
  </main>
  <script>
    document.getElementById("dbPath").value = {db_path};

    function value(id) {{
      return document.getElementById(id).value;
    }}

    function setStatus(text) {{
      document.getElementById("status").textContent = text;
    }}

    function appendLog(text) {{
      const area = document.getElementById("logText");
      const timestamp = new Date().toISOString();
      area.value += `[${{timestamp}}] ${{text}}\\n`;
      area.scrollTop = area.scrollHeight;
    }}

    function setBusy(busy) {{
      document.querySelectorAll("button").forEach((button) => {{
        button.disabled = busy;
      }});
    }}

    async function runAction(action, label, payload) {{
      setBusy(true);
      setStatus(`${{label}}を実行中...`);
      appendLog(`開始: ${{label}}`);
      try {{
        const response = await fetch("/api/action", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ action, ...payload }})
        }});
        const data = await response.json();
        if (!response.ok || !data.ok) {{
          throw new Error(data.error || `リクエストに失敗しました: HTTP ${{response.status}}`);
        }}
        appendLog(data.message);
        setStatus("待機中");
        if (data.result_text) {{
          document.getElementById("resultText").value = data.result_text;
        }}
      }} catch (error) {{
        appendLog(`失敗: ${{label}} / ${{error.message}}`);
        setStatus(`${{label}}に失敗しました`);
        window.alert(error.message);
      }} finally {{
        setBusy(false);
      }}
    }}
  </script>
</body>
</html>"""
