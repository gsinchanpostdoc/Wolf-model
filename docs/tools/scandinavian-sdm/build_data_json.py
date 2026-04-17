"""
build_data_json.py
Regenerate data/data.json from data/map_data.parquet for the native browser build.

Run locally whenever the parquet is updated:
    python build_data_json.py

The native index.html fetches data/data.json. GitHub Pages gzips it on the wire
(~500 KB compressed for ~6.7 MB raw). No pyarrow runtime is required in the
browser.

Author: Dr. Sinchan Ghosh, 2026.
"""

from __future__ import annotations

import json
import os
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas is required. Install with: pip install pandas fastparquet")

SCENARIOS = ["historical", "ssp119", "ssp126", "ssp245", "ssp370", "ssp585"]
VARIABLES = [
    "NT", "WP_total", "W_solitary", "n_territories", "mean_ST",
    "WD", "D_roe", "D_moose", "H",
    "pred_wolf_density", "pred_roe_density", "pred_moose_density",
]


def _round(v: float) -> float | None:
    return None if pd.isna(v) else round(float(v), 4)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "data", "map_data.parquet")
    dst = os.path.join(here, "data", "data.json")
    if not os.path.exists(src):
        sys.exit(f"Missing source parquet: {src}")

    try:
        df = pd.read_parquet(src, engine="fastparquet")
    except Exception:
        df = pd.read_parquet(src)  # fall back to pyarrow if installed locally

    df = df.sort_values(["scenario", "year", "GridID"]).reset_index(drop=True)

    grids = (
        df[["GridID", "centroid_lat", "centroid_lon", "country", "county"]]
        .drop_duplicates("GridID")
        .sort_values("GridID")
        .rename(columns={"GridID": "id", "centroid_lat": "lat", "centroid_lon": "lon"})
        .to_dict(orient="records")
    )

    payload = {
        "meta": {
            "variables": VARIABLES,
            "scenarios": SCENARIOS,
            "map_year_min": 2025,
            "map_year_max": 2060,
            "ts_year_min": int(df.year.min()),
            "ts_year_max": int(df.year.max()),
        },
        "grids": grids,
        "gridId": df.GridID.astype(int).tolist(),
        "year": df.year.astype(int).tolist(),
        "scenarioIdx": df.scenario.map({s: i for i, s in enumerate(SCENARIOS)}).astype(int).tolist(),
    }
    for v in VARIABLES:
        payload[v] = [_round(x) for x in df[v].tolist()]

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))

    kb = os.path.getsize(dst) / 1024
    print(f"Wrote {dst} ({kb:.1f} KB, {len(df):,} rows). "
          f"GitHub Pages will gzip this to ~{kb/14:.0f} KB on the wire.")


if __name__ == "__main__":
    main()
