# nutrition-database

ローカル Python CLI で、日次の栄養ターゲットを満たす最安の食品組み合わせを求めるツールです。

## 構成

```text
project_root/
  AGENTS.md
  README.md
  requirements.txt
  src/
    ingest/
    normalize/
    optimize/
    export/
    db/
    cli/
    gui/
  tests/
  data/
    raw/
    processed/
  outputs/
```

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 起動方法

セットアップ後は、まず仮想環境を有効化してから起動します。

### GUI を起動する

```bash
source .venv/bin/activate
python -m src.cli.main launch-gui
```

`tkinter` が使える環境ではデスクトップウィンドウで起動し、使えない環境ではローカルのブラウザ画面で起動します。

### CLI で使い始める

```bash
source .venv/bin/activate
python -m src.cli.main --help
```

## 使い方

全コマンドは `python -m src.cli.main` で実行します。DB パスは省略時に `data/processed/nutrition.db` を使います。
このリポジトリには、動作確認用の最小サンプル入力を `data/raw/` に同梱しています。

### GUI 起動

ローカル GUI を起動します。`tkinter` が使える環境ではデスクトップウィンドウを開き、使えない環境ではローカルのブラウザ GUI に自動フォールバックします。内部では既存の CLI と同じ処理関数を呼び出します。

```bash
python -m src.cli.main launch-gui
```

別の DB を使う場合:

```bash
python -m src.cli.main --db data/processed/demo.db launch-gui
```

### DB 初期化

```bash
python -m src.cli.main init-db
```

### MEXT 取り込み

同梱済みサンプル:

```bash
python -m src.cli.main ingest-mext --input data/raw/mext.xlsx
```

### e-Stat 取り込み

同梱済みサンプル:

```bash
python -m src.cli.main ingest-estat --input data/raw/estat.csv
```

### Open Food Facts 同期

Open Food Facts ではまず `Search-a-licious` 検索を使い、結果が空なら旧検索 API に切り替えます。外部 API の状態によって取得件数は変わります。

```bash
python -m src.cli.main sync-off-products --query オートミール
```

### Open Prices 同期

日本円 (`JPY`) の価格だけを取り込みます。`1g あたりの価格` に正規化できない価格は最適化対象から除外されます。
同梱サンプルではなく外部 API の実データを使うため、存在する商品コードを指定してください。
2026-04-22 時点で動作確認した例:

```bash
python -m src.cli.main sync-open-prices --product-code 4902621003681
```

### 食品マッピング

自動マッピング:

```bash
python -m src.cli.main map-foods --auto
```

手動マッピング CSV:

```csv
from_source_type,from_source_key,to_food_id,mapping_confidence
estat,こめ,mext_1001,1.0
```

```bash
python -m src.cli.main map-foods --manual data/raw/manual_mapping.csv
```

### 最適化を実行する

ユーザー定義の栄養ターゲット JSON 例:

```json
{
  "targets": [
    {"nutrient_id": "energy_kcal", "min": 1800, "max": 2200},
    {"nutrient_id": "protein_g", "min": 80},
    {"nutrient_id": "fat_g", "min": 40, "max": 70},
    {"nutrient_id": "iron_mg", "min": 10},
    {"nutrient_id": "vitamin_c_mg", "min": 100}
  ]
}
```

```bash
python -m src.cli.main solve-diet --targets data/raw/targets.json --output outputs/solution.json
```

最小サンプルを最初から順に実行する場合:

```bash
python -m src.cli.main init-db
python -m src.cli.main ingest-mext --input data/raw/mext.xlsx
python -m src.cli.main ingest-estat --input data/raw/estat.csv
python -m src.cli.main map-foods --auto
python -m src.cli.main solve-diet --targets data/raw/targets.json --output outputs/solution.json
cat outputs/solution.json
```

### CSV を出力する

```bash
python -m src.cli.main export-csv --output-dir outputs/csv
```

未対応付けデータだけ出力する場合:

```bash
python -m src.cli.main export-unmatched --output outputs/unmatched.csv
```

## 入力ファイルの前提

### MEXT

- `.xlsx` / `.xlsm`
- ヘッダ行に `食品名` と対象栄養素列があること

### e-Stat

- `.csv` / `.xlsx` / `.xlsm`
- 少なくとも `name`, `price`, `quantity_value`, `quantity_unit` 相当の列があること
- `quantity_text` のような単一列でも `2 x 100 g` の形なら読めます

## 出力

`solve-diet` は JSON を出力します。主要フィールドは次のとおりです。

- `status`
  値は `optimal`、`infeasible`、`error` のいずれかです
- `total_cost_yen`
- `foods`
- `nutrients`
- `excluded_foods_count`
- `notes`

`export-csv` は次の CSV を出力します。

- `normalized_foods.csv`
- `normalized_prices.csv`
- `normalized_nutrients.csv`
- `unmatched_mapping_candidates.csv`

## テスト

```bash
PYTHONPATH=. pytest
```
