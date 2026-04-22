from __future__ import annotations

import json
import queue
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

from src.db.connection import DEFAULT_DB_PATH, ensure_database, get_connection
from src.export.csv_export import export_all_csv, export_unmatched_csv
from src.ingest.estat import import_estat
from src.ingest.mext import import_mext
from src.ingest.open_food_facts import sync_products
from src.ingest.open_prices import sync_prices_for_product
from src.normalize.mapping import auto_map_foods, manual_map_foods
from src.optimize.solver import solve_diet_to_file

TaskResult = tuple[str, str, object]


class NutritionDatabaseApp(tk.Tk):
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        super().__init__()
        self.title("nutrition-database 操作画面")
        self.geometry("1080x760")
        self.minsize(960, 680)

        self._task_queue: queue.Queue[TaskResult] = queue.Queue()
        self._buttons: list[ttk.Button] = []
        self._busy = False

        self.db_path_var = tk.StringVar(value=str(db_path))
        self.mext_input_var = tk.StringVar(value="data/raw/mext.xlsx")
        self.estat_input_var = tk.StringVar(value="data/raw/estat.csv")
        self.off_query_var = tk.StringVar(value="オートミール")
        self.product_code_var = tk.StringVar(value="")
        self.manual_mapping_var = tk.StringVar(value="data/raw/manual_mapping.csv")
        self.targets_var = tk.StringVar(value="data/raw/targets.json")
        self.solution_output_var = tk.StringVar(value="outputs/solution.json")
        self.csv_output_dir_var = tk.StringVar(value="outputs/csv")
        self.unmatched_output_var = tk.StringVar(value="outputs/unmatched.csv")
        self.status_var = tk.StringVar(value="待機中")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        self._build_db_controls()
        self._build_notebook()
        self._build_output_area()
        self.after(150, self._poll_task_queue)

    def _build_db_controls(self) -> None:
        frame = ttk.Frame(self, padding=(12, 12, 12, 6))
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="SQLite データベース").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(frame, textvariable=self.db_path_var).grid(row=0, column=1, sticky="ew")
        self._register_button(
            ttk.Button(frame, text="参照", command=self._choose_db_path),
            row=0,
            column=2,
            padx=(8, 8),
        )
        self._register_button(
            ttk.Button(frame, text="DB を初期化", command=self._run_init_db),
            row=0,
            column=3,
        )

    def _build_notebook(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)

        imports_tab = ttk.Frame(notebook, padding=12)
        sync_tab = ttk.Frame(notebook, padding=12)
        mapping_tab = ttk.Frame(notebook, padding=12)
        solve_tab = ttk.Frame(notebook, padding=12)
        export_tab = ttk.Frame(notebook, padding=12)

        notebook.add(imports_tab, text="取り込み")
        notebook.add(sync_tab, text="同期")
        notebook.add(mapping_tab, text="マッピング")
        notebook.add(solve_tab, text="最適化")
        notebook.add(export_tab, text="出力")

        for tab in (imports_tab, sync_tab, mapping_tab, solve_tab, export_tab):
            tab.columnconfigure(1, weight=1)

        self._build_import_tab(imports_tab)
        self._build_sync_tab(sync_tab)
        self._build_mapping_tab(mapping_tab)
        self._build_solve_tab(solve_tab)
        self._build_export_tab(export_tab)

    def _build_import_tab(self, parent: ttk.Frame) -> None:
        self._build_file_row(
            parent,
            row=0,
            label="MEXT ファイル",
            variable=self.mext_input_var,
            browse=self._choose_mext_file,
            action=("MEXT を取り込む", self._run_import_mext),
        )
        self._build_file_row(
            parent,
            row=1,
            label="e-Stat ファイル",
            variable=self.estat_input_var,
            browse=self._choose_estat_file,
            action=("e-Stat を取り込む", self._run_import_estat),
        )

    def _build_sync_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Open Food Facts の検索語").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(parent, textvariable=self.off_query_var).grid(row=0, column=1, sticky="ew", pady=6)
        self._register_button(
            ttk.Button(parent, text="OFF 商品を同期", command=self._run_sync_off_products),
            row=0,
            column=2,
            pady=6,
        )

        ttk.Label(parent, text="商品のバーコード").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(parent, textvariable=self.product_code_var).grid(row=1, column=1, sticky="ew", pady=6)
        self._register_button(
            ttk.Button(parent, text="Open Prices を同期", command=self._run_sync_open_prices),
            row=1,
            column=2,
            pady=6,
        )

    def _build_mapping_tab(self, parent: ttk.Frame) -> None:
        ttk.Label(
            parent,
            text="自動マッピングでは、完全一致と保守的な正規化名一致だけを使います。",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        self._register_button(
            ttk.Button(parent, text="自動マッピングを実行", command=self._run_auto_mapping),
            row=1,
            column=0,
            sticky="w",
            pady=6,
        )
        self._build_file_row(
            parent,
            row=2,
            label="手動マッピング CSV",
            variable=self.manual_mapping_var,
            browse=self._choose_manual_mapping_file,
            action=("手動マッピングを反映", self._run_manual_mapping),
        )

    def _build_solve_tab(self, parent: ttk.Frame) -> None:
        self._build_file_row(
            parent,
            row=0,
            label="ターゲット JSON",
            variable=self.targets_var,
            browse=self._choose_targets_file,
            action=None,
        )
        self._build_file_row(
            parent,
            row=1,
            label="結果 JSON",
            variable=self.solution_output_var,
            browse=self._choose_solution_output,
            action=("最適化を実行", self._run_solve_diet),
        )

    def _build_export_tab(self, parent: ttk.Frame) -> None:
        self._build_file_row(
            parent,
            row=0,
            label="CSV 出力先ディレクトリ",
            variable=self.csv_output_dir_var,
            browse=self._choose_csv_output_dir,
            action=("CSV を出力", self._run_export_csv),
        )
        self._build_file_row(
            parent,
            row=1,
            label="未対応付け CSV",
            variable=self.unmatched_output_var,
            browse=self._choose_unmatched_output,
            action=("未対応付け一覧を出力", self._run_export_unmatched),
        )

    def _build_output_area(self) -> None:
        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        result_frame = ttk.LabelFrame(paned, text="結果プレビュー", padding=8)
        log_frame = ttk.LabelFrame(paned, text="実行ログ", padding=8)
        paned.add(result_frame, weight=3)
        paned.add(log_frame, weight=2)

        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.result_text = ScrolledText(result_frame, wrap=tk.WORD, height=14)
        self.result_text.grid(row=0, column=0, sticky="nsew")
        self.result_text.configure(state="disabled")

        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, height=14)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

        status_bar = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 0, 12, 8))
        status_bar.grid(row=3, column=0, sticky="ew")

    def _build_file_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        browse: Callable[[], None],
        action: tuple[str, Callable[[], None]] | None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=6)
        self._register_button(
            ttk.Button(parent, text="参照", command=browse),
            row=row,
            column=2,
            padx=(8, 8),
            pady=6,
        )
        if action is not None:
            self._register_button(
                ttk.Button(parent, text=action[0], command=action[1]),
                row=row,
                column=3,
                pady=6,
            )

    def _register_button(self, button: ttk.Button, **grid_kwargs: object) -> None:
        self._buttons.append(button)
        button.grid(**grid_kwargs)

    def _choose_db_path(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="SQLite データベースの保存先を選択",
            defaultextension=".db",
            initialfile=Path(self.db_path_var.get()).name or "nutrition.db",
            filetypes=[("SQLite データベース", "*.db"), ("すべてのファイル", "*.*")],
        )
        if selected:
            self.db_path_var.set(selected)

    def _choose_mext_file(self) -> None:
        self._choose_open_file(self.mext_input_var, [("Excel ファイル", "*.xlsx *.xlsm"), ("すべてのファイル", "*.*")])

    def _choose_estat_file(self) -> None:
        self._choose_open_file(
            self.estat_input_var,
            [("CSV または Excel", "*.csv *.xlsx *.xlsm"), ("すべてのファイル", "*.*")],
        )

    def _choose_manual_mapping_file(self) -> None:
        self._choose_open_file(self.manual_mapping_var, [("CSV ファイル", "*.csv"), ("すべてのファイル", "*.*")])

    def _choose_targets_file(self) -> None:
        self._choose_open_file(self.targets_var, [("JSON ファイル", "*.json"), ("すべてのファイル", "*.*")])

    def _choose_solution_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="結果 JSON の保存先を選択",
            defaultextension=".json",
            initialfile=Path(self.solution_output_var.get()).name or "solution.json",
            filetypes=[("JSON ファイル", "*.json"), ("すべてのファイル", "*.*")],
        )
        if selected:
            self.solution_output_var.set(selected)

    def _choose_csv_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="CSV の出力先ディレクトリを選択")
        if selected:
            self.csv_output_dir_var.set(selected)

    def _choose_unmatched_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            title="未対応付け CSV の保存先を選択",
            defaultextension=".csv",
            initialfile=Path(self.unmatched_output_var.get()).name or "unmatched.csv",
            filetypes=[("CSV ファイル", "*.csv"), ("すべてのファイル", "*.*")],
        )
        if selected:
            self.unmatched_output_var.set(selected)

    def _choose_open_file(self, variable: tk.StringVar, filetypes: list[tuple[str, str]]) -> None:
        selected = filedialog.askopenfilename(
            title="ファイルを選択",
            initialfile=Path(variable.get()).name or "",
            filetypes=filetypes,
        )
        if selected:
            variable.set(selected)

    def _db_path(self) -> Path:
        db_path = self.db_path_var.get().strip()
        if not db_path:
            raise ValueError("SQLite データベースのパスを入力してください")
        return Path(db_path)

    def _require_path(self, value: str, label: str) -> Path:
        text = value.strip()
        if not text:
            raise ValueError(f"{label}を入力してください")
        return Path(text)

    def _run_init_db(self) -> None:
        try:
            db_path = self._db_path()
        except ValueError as exc:
            self._show_input_error(exc)
            return
        self._run_task(
            "DB 初期化",
            lambda: {"message": f"データベースを初期化しました: {ensure_database(db_path)}"},
        )

    def _run_import_mext(self) -> None:
        try:
            db_path = self._db_path()
            input_path = self._require_path(self.mext_input_var.get(), "MEXT ファイル")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = import_mext(conn, input_path)
            return {"message": f"MEXT データを {imported} 件取り込みました: {input_path}"}

        self._run_task("MEXT 取り込み", worker)

    def _run_import_estat(self) -> None:
        try:
            db_path = self._db_path()
            input_path = self._require_path(self.estat_input_var.get(), "e-Stat ファイル")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = import_estat(conn, input_path)
            return {"message": f"e-Stat データを {imported} 件取り込みました: {input_path}"}

        self._run_task("e-Stat 取り込み", worker)

    def _run_sync_off_products(self) -> None:
        try:
            db_path = self._db_path()
            query = self.off_query_var.get().strip()
            if not query:
                raise ValueError("Open Food Facts の検索語を入力してください")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = sync_products(conn, query)
            return {"message": f"Open Food Facts の商品を {imported} 件取り込みました: 検索語={query}"}

        self._run_task("OFF 商品同期", worker)

    def _run_sync_open_prices(self) -> None:
        try:
            db_path = self._db_path()
            product_code = self.product_code_var.get().strip()
            if not product_code:
                raise ValueError("商品のバーコードを入力してください")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = sync_prices_for_product(conn, product_code)
            return {"message": f"Open Prices の価格情報を {imported} 件取り込みました: バーコード={product_code}"}

        self._run_task("Open Prices 同期", worker)

    def _run_auto_mapping(self) -> None:
        try:
            db_path = self._db_path()
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = auto_map_foods(conn)
            return {"message": f"自動マッピングを {imported} 件作成しました"}

        self._run_task("自動マッピング", worker)

    def _run_manual_mapping(self) -> None:
        try:
            db_path = self._db_path()
            input_path = self._require_path(self.manual_mapping_var.get(), "手動マッピング CSV")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                imported = manual_map_foods(conn, input_path)
            return {"message": f"手動マッピングを {imported} 件反映しました: {input_path}"}

        self._run_task("手動マッピング", worker)

    def _run_solve_diet(self) -> None:
        try:
            db_path = self._db_path()
            targets_path = self._require_path(self.targets_var.get(), "ターゲット JSON")
            output_path = self._require_path(self.solution_output_var.get(), "結果 JSON")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                result = solve_diet_to_file(conn, targets_path, output_path)
            preview = json.dumps(result, ensure_ascii=False, indent=2)
            return {
                "message": f"最適化結果 ({result['status']}) を出力しました: {output_path}",
                "result_text": preview,
            }

        self._run_task("最適化", worker)

    def _run_export_csv(self) -> None:
        try:
            db_path = self._db_path()
            output_dir = self._require_path(self.csv_output_dir_var.get(), "CSV 出力先ディレクトリ")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                outputs = export_all_csv(conn, output_dir)
            return {
                "message": f"正規化済み CSV を出力しました: {output_dir}",
                "result_text": json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False, indent=2),
            }

        self._run_task("CSV 出力", worker)

    def _run_export_unmatched(self) -> None:
        try:
            db_path = self._db_path()
            output_path = self._require_path(self.unmatched_output_var.get(), "未対応付け CSV")
        except ValueError as exc:
            self._show_input_error(exc)
            return

        def worker() -> dict[str, object]:
            db_file = ensure_database(db_path)
            with get_connection(db_file) as conn:
                exported = export_unmatched_csv(conn, output_path)
            return {"message": f"未対応付け一覧を出力しました: {exported}"}

        self._run_task("未対応付け一覧出力", worker)

    def _run_task(self, task_name: str, worker: Callable[[], dict[str, object]]) -> None:
        if self._busy:
            messagebox.showinfo("処理中", "別の処理を実行中です。完了するまでお待ちください。")
            return
        self._set_busy(True, f"{task_name}を実行中...")
        self._append_log(f"開始: {task_name}")

        def target() -> None:
            try:
                payload = worker()
                self._task_queue.put(("success", task_name, payload))
            except Exception as exc:  # pragma: no cover - exercised via GUI runtime
                self._task_queue.put(("error", task_name, str(exc)))

        thread = threading.Thread(target=target, daemon=True)
        thread.start()

    def _poll_task_queue(self) -> None:
        try:
            status, task_name, payload = self._task_queue.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_task_queue)
            return
        if status == "success":
            details = payload if isinstance(payload, dict) else {}
            message = str(details.get("message") or f"{task_name}が完了しました")
            self._append_log(message)
            result_text = details.get("result_text")
            if result_text:
                self._set_result_text(str(result_text))
            self._set_busy(False, "待機中")
        else:
            error_text = str(payload)
            self._append_log(f"失敗: {task_name} / {error_text}")
            self._set_busy(False, f"{task_name}に失敗しました")
            messagebox.showerror("処理に失敗しました", f"{task_name}に失敗しました。\n\n{error_text}")
        self.after(150, self._poll_task_queue)

    def _set_busy(self, busy: bool, status_text: str) -> None:
        self._busy = busy
        self.status_var.set(status_text)
        state = "disabled" if busy else "normal"
        for button in self._buttons:
            button.configure(state=state)

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _set_result_text(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _show_input_error(self, exc: Exception) -> None:
        self.status_var.set("入力エラー")
        self._append_log(f"入力エラー: {exc}")
        messagebox.showerror("入力エラー", str(exc))
