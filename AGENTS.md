# AGENTS.md

## Source of truth
This file is the implementation specification for the project.
Codex must treat this file as the source of truth for v1.
Do not add UI, web frontend, or API server work unless explicitly required by a later prompt.
Prefer the smallest implementation that satisfies all acceptance criteria.

## Project goal
Build a local Python CLI tool that computes the cheapest combination of foods that satisfies user-defined daily nutrition targets.

The optimizer must combine three data sources:
1. e-Stat retail price data for basic foods
2. MEXT food composition data for nutrient values
3. Open Food Facts and Open Prices for packaged products

## Scope for v1
Implement backend and CLI only.

In scope:
- local Python project
- SQLite database
- data ingestion from local files and remote APIs
- normalization of price and nutrient units
- food mapping across sources
- linear programming based optimization
- JSON output for solution results
- CSV export for intermediate tables

Out of scope:
- any UI
- web app
- authentication
- background jobs
- recommendation explanations beyond minimal output fields
- regional adjustment logic
- sale price logic
- taste, satiety, cooking time, shelf life
- allergy handling
- meal scheduling across multiple days

## Required stack
Use Python.
Use SQLite for storage.
Use a linear programming solver available from Python.
Use a simple CLI interface.
Keep dependencies minimal.

Suggested libraries if needed:
- pandas
- openpyxl
- requests
- pydantic
- typer or argparse
- pulp or scipy.optimize
- sqlite3 from stdlib

## Repository layout
Create this structure:

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

## Functional requirements

### 1. Ingestion
Implement commands for:
- importing e-Stat retail price data from local CSV or Excel
- importing MEXT food composition data from local Excel
- fetching product nutrition from Open Food Facts API
- fetching product prices from Open Prices API

CLI commands must exist at minimum in equivalent form:
- `ingest-estat --input <path>`
- `ingest-mext --input <path>`
- `sync-off-products --query <text>`
- `sync-open-prices --product-code <barcode>`

Do not require API access for e-Stat or MEXT in v1.
Prefer file import for those two sources.

### 2. Storage model
Create these tables.

#### foods
- `food_id` TEXT PRIMARY KEY
- `name` TEXT NOT NULL
- `source_type` TEXT NOT NULL
- `source_key` TEXT NOT NULL
- `canonical_name` TEXT
- `default_unit` TEXT NOT NULL
- `edible_ratio` REAL DEFAULT 1.0
- `is_active` INTEGER NOT NULL DEFAULT 1

Allowed `source_type` values:
- `estat`
- `mext`
- `off`

Allowed `default_unit` values:
- `g`
- `ml`
- `piece`

#### nutrients
- `nutrient_id` TEXT PRIMARY KEY
- `name` TEXT NOT NULL
- `unit` TEXT NOT NULL

Minimum supported nutrients:
- `energy_kcal`
- `protein_g`
- `fat_g`
- `carb_g`
- `fiber_g`
- `calcium_mg`
- `iron_mg`
- `vitamin_a_ug`
- `vitamin_b1_mg`
- `vitamin_b2_mg`
- `vitamin_c_mg`

#### food_nutrients
- `food_id` TEXT NOT NULL
- `nutrient_id` TEXT NOT NULL
- `amount_per_100g` REAL NOT NULL
- primary key on `food_id`, `nutrient_id`

#### food_prices
- `food_id` TEXT NOT NULL
- `price_yen` REAL NOT NULL
- `quantity_value` REAL NOT NULL
- `quantity_unit` TEXT NOT NULL
- `price_per_g` REAL
- `observed_at` TEXT
- `source_detail` TEXT
- primary key on `food_id`, `observed_at`, `source_detail`

#### food_mapping
- `mapping_id` TEXT PRIMARY KEY
- `from_source_type` TEXT NOT NULL
- `from_source_key` TEXT NOT NULL
- `to_food_id` TEXT NOT NULL
- `mapping_confidence` REAL NOT NULL
- `mapping_method` TEXT NOT NULL

Allowed `mapping_method` values:
- `exact`
- `manual`
- `heuristic`

#### nutrient_targets
- `target_id` TEXT PRIMARY KEY
- `nutrient_id` TEXT NOT NULL
- `min_value` REAL
- `max_value` REAL

### 3. Normalization rules
Apply all of the following.

#### Common rules
- normalize all nutrient values to `per 100g`
- normalize all prices to `yen per g`
- exclude foods that cannot produce `price_per_g`
- exclude foods with no nutrient data
- if only `piece` is available and no reliable weight conversion exists, exclude from optimization

#### e-Stat rules
- treat e-Stat prices as representative prices, not store-specific live prices
- if multiple price records exist for one food, use the latest record in v1

#### MEXT rules
- treat MEXT values as the canonical base for basic foods
- use MEXT food names as the basis for `canonical_name`
- if multiple candidate matches exist, do not auto-resolve aggressively; leave unmatched instead

#### Open Food Facts and Open Prices rules
- packaged products remain independent food items
- do not forcibly merge packaged products into MEXT foods
- only create price-attached packaged candidates when a price is available

### 4. Mapping
Implement two mapping modes:
- auto mapping by exact or conservative normalized-name matching
- manual mapping by CSV override file

Commands must exist at minimum in equivalent form:
- `map-foods --auto`
- `map-foods --manual <path>`

Also implement a command or export that lists unmatched records.

### 5. Optimization
Model each food amount as a continuous variable `x_i` in grams per day.

Objective:
- minimize total cost
- `sum(price_per_g_i * x_i)`

Constraints:
- `x_i >= 0`
- for each nutrient with a lower bound: satisfy the minimum
- for each nutrient with an upper bound: do not exceed the maximum

Use nutrient density converted from `amount_per_100g` to `amount_per_g` inside the solver.

Support optional per-food upper bounds if easy to implement, but do not make them mandatory for v1.

### 6. User-defined nutrition targets
The system must allow the user to define their own daily nutrient requirements.
Do not hardcode national reference values into solver logic.
Targets must be provided by an external JSON file.

Example format:

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

CLI command must exist at minimum in equivalent form:
- `solve-diet --targets <path> --output <path>`

### 7. Output
The optimization result must be written as JSON.

Required fields:
- `status` with one of `optimal`, `infeasible`, `error`
- `total_cost_yen`
- `foods` array with:
  - `food_id`
  - `name`
  - `amount_g`
  - `cost_yen`
- `nutrients` array with:
  - `nutrient_id`
  - `actual`
  - `target_min`
  - `target_max`
- `excluded_foods_count`
- `notes`

Example shape:

```json
{
  "status": "optimal",
  "total_cost_yen": 412.3,
  "foods": [
    {"food_id": "mext_rice_001", "name": "こめ", "amount_g": 320, "cost_yen": 96.0},
    {"food_id": "off_4900000000000", "name": "オートミール", "amount_g": 80, "cost_yen": 58.4}
  ],
  "nutrients": [
    {"nutrient_id": "protein_g", "actual": 67.2, "target_min": 60, "target_max": null}
  ],
  "excluded_foods_count": 154,
  "notes": ["price missing foods excluded"]
}
```

### 8. Export
Provide a way to dump normalized intermediate tables to CSV.
At minimum, export:
- normalized foods
- normalized prices
- normalized nutrients
- unmatched mapping candidates

## Non-functional requirements
- deterministic behavior for the same inputs
- UTF-8 everywhere
- ISO 8601 for timestamps
- clear logging to stdout or stderr
- if remote fetch fails, local already-ingested data must still be usable
- fail fast on malformed inputs with readable error messages

## Acceptance criteria
v1 is complete only if all of the following are true:
1. can import at least one e-Stat price file
2. can import at least one MEXT composition file
3. can fetch at least one Open Food Facts product
4. can fetch at least one Open Prices record and attach it to a product
5. can solve an optimization problem from a user-supplied targets JSON file
6. returns `optimal` or `infeasible` as structured JSON
7. automatically excludes foods missing either price or nutrient data
8. can export unmatched mappings and normalized tables

## Implementation priorities
Implement in this order:
1. database schema and seed nutrients
2. MEXT import
3. e-Stat import
4. normalization pipeline
5. optimization solver
6. JSON result export
7. Open Food Facts sync
8. Open Prices sync
9. conservative auto-mapping and manual override support
10. tests

## Testing requirements
Write tests for:
- schema creation
- unit normalization
- price normalization
- exclusion logic
- JSON target parsing
- feasible optimization case
- infeasible optimization case
- mapping override behavior

Prefer a small synthetic fixture dataset for tests.
Do not depend on live APIs for core tests.

## Constraints on Codex behavior
- do not add UI code
- do not broaden scope
- do not silently invent nutrition reference values
- do not over-engineer matching logic
- prefer conservative mapping over incorrect mapping
- keep code modular and readable
- document all CLI commands in README.md

## Definition of done
The project is done when a user can:
1. import raw price and nutrient data
2. optionally fetch packaged products and prices
3. define their own daily nutrient targets in JSON
4. run one CLI command to solve for the cheapest daily diet
5. receive machine-readable JSON output with foods, cost, and nutrient totals
