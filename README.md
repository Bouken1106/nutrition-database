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

## CLI

全コマンドは `python -m src.cli.main` で実行します。DB パスは省略時に `data/processed/nutrition.db` を使います。

### DB 初期化

```bash
python -m src.cli.main init-db
```

### MEXT 取り込み

```bash
python -m src.cli.main ingest-mext --input data/raw/mext.xlsx
```

### e-Stat 取り込み

```bash
python -m src.cli.main ingest-estat --input data/raw/estat.csv
```

### Open Food Facts 同期

```bash
python -m src.cli.main sync-off-products --query オートミール
```

### Open Prices 同期

`JPY` の価格だけを取り込みます。`yen per g` に正規化できない価格は最適化対象から除外されます。

```bash
python -m src.cli.main sync-open-prices --product-code 4900000000000
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

### 解く

ターゲット JSON 例:

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

### CSV エクスポート

```bash
python -m src.cli.main export-csv --output-dir outputs/csv
```

未一致だけ出す場合:

```bash
python -m src.cli.main export-unmatched --output outputs/unmatched.csv
```

## 入力フォーマットの前提

### MEXT

- `.xlsx` / `.xlsm`
- ヘッダ行に `食品名` と対象栄養素列があること

### e-Stat

- `.csv` / `.xlsx` / `.xlsm`
- 少なくとも `name`, `price`, `quantity_value`, `quantity_unit` 相当の列があること
- `quantity_text` のような単一列でも `2 x 100 g` の形なら読めます

## 出力

`solve-diet` は JSON を出力します。主要フィールド:

- `status`
- `total_cost_yen`
- `foods`
- `nutrients`
- `excluded_foods_count`
- `notes`

`export-csv` は以下を出力します。

- `normalized_foods.csv`
- `normalized_prices.csv`
- `normalized_nutrients.csv`
- `unmatched_mapping_candidates.csv`

## テスト

```bash
pytest
```

