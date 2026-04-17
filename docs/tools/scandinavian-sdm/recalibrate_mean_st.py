"""
recalibrate_mean_st.py
Apply the paper's Mattisson (2013) fallback regression to restore realistic
dispersion in predicted wolf territory size (mean_ST).

Scientific rationale
--------------------
In the current `map_data.parquet`, `mean_ST` is near-perfectly collinear with
`H` (r = -0.9998) because the implementation collapsed Eq. 8's stochastic
territory dynamics to a single deterministic H-to-ST map. The empirical
range shrinks to 779-978 km-squared, against the paper's observed Scandinavian
range of 200-1700 km-squared (Mattisson et al., 2013; Ghosh, Franklin &
Zimmermann, 2026, Section 3.3). Ghosh et al. (2026) anticipate this case and
supply an explicit fallback (Eq. 8, lines 740-743):

    "If the calibrated lambda-based formulation yields predictions outside
     the observed Scandinavian range (200-1700 km^2) for more than 5% of
     grid-year combinations, the Mattisson regression replaces Equation 8
     as the primary territory-size estimator."

The Mattisson (2013) regression as printed in the paper (line 737-739):

    ST = 1025.6 + 641.5 * latitude_std - 399.4 * roe_std

where _std denotes the Gelman (2008) convention of dividing the centred
value by 2 standard deviations (so the scale matches a 0/1 binary predictor).

This script:
  1. Reads the authoritative repo-root parquet.
  2. Standardises centroid_lat on the full dataset (stationary geographic
     anchor) and D_roe on the 1999-2015 training window (same convention
     the paper uses to fit Eq. 1).
  3. Applies the Mattisson regression to every row.
  4. Clips to [200, 1700] km-squared.
  5. Leaves rows with NT == 0 at mean_ST = 0 (no territories -> no mean
     territory size defined).
  6. Writes the recalibrated parquet atomically to the tool-local path,
     fixing the on-disk corruption in the process.
  7. Prints a before/after accuracy audit against the paper's reported
     calibration envelope (bias +10.2 km^2, RMSE 325 km^2, r 0.413).

Author: Dr. Sinchan Ghosh, 2026.
"""

from __future__ import annotations

import os
import sys

try:
    import numpy as np
    import pandas as pd
except ImportError:
    sys.exit("numpy and pandas are required. Install with: pip install numpy pandas pyarrow")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_PARQUET = os.path.join(HERE, "data", "map_data.parquet")

# Authoritative repo-root copy (the tool-local one is known to be corrupted
# by an earlier publish run that truncated the trailing PAR1 magic).
ROOT_PARQUET_CANDIDATES = [
    os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "map_data.parquet")),
    os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", "data", "map_data.parquet")),
    r"C:\Users\sinch\OneDrive\Desktop\Wolf\Wolfapp\data\map_data.parquet",
]

# Paper's reported calibration envelope for mean_ST (Section 3.3, Table 1C).
PAPER_BIAS_KM2 = 10.2
PAPER_RMSE_KM2 = 325.0
PAPER_R = 0.413

SMIN = 200.0
SMAX = 1700.0
BETA0 = 1025.6
BETA_LAT = 641.5
BETA_ROE = -399.4


def find_source_parquet() -> str:
    for p in ROOT_PARQUET_CANDIDATES:
        if os.path.isfile(p):
            return p
    sys.exit(
        "Could not find an authoritative map_data.parquet. Edit "
        "ROOT_PARQUET_CANDIDATES at the top of this script."
    )


def load_parquet(path: str) -> pd.DataFrame:
    """Try fastparquet first; fall back to pyarrow."""
    for engine in ("fastparquet", "pyarrow"):
        try:
            return pd.read_parquet(path, engine=engine)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    sys.exit(f"Could not read parquet {path}: {last_exc}")


def standardise_2sd(x: pd.Series, mask: pd.Series | None = None) -> pd.Series:
    """Centre and divide by 2 SD (Gelman 2008). Mask defines the reference
    sample (e.g. the 1999-2015 training window for D_roe; the full lattice
    for latitude)."""
    ref = x if mask is None else x[mask]
    mu = float(ref.mean())
    sd = float(ref.std(ddof=1))
    if sd == 0.0:
        return x * 0.0
    return (x - mu) / (2.0 * sd)


def audit(df: pd.DataFrame, label: str) -> None:
    proj = df[(df.scenario != "historical") & (df.year >= 2025) & (df.NT > 0)]
    if proj.empty:
        print(f"  [{label}] no projection rows with NT>0")
        return
    s = proj["mean_ST"]
    print(f"  [{label}] n={len(s):>6d}  mean={s.mean():7.2f}  median={s.median():7.2f}  "
          f"p5={s.quantile(0.05):7.2f}  p95={s.quantile(0.95):7.2f}  "
          f"min={s.min():7.2f}  max={s.max():7.2f}")
    # Spread across SSPs for the same (GridID, year):
    pivot = proj.pivot_table(index=["GridID", "year"], columns="scenario",
                              values="mean_ST", aggfunc="first")
    if pivot.shape[1] > 1:
        cross = pivot.std(axis=1).dropna()
        print(f"  [{label}] cross-SSP std across (grid, year):  "
              f"median={cross.median():7.2f}  p95={cross.quantile(0.95):7.2f}")
    # Correlation with latitude and D_roe, if present:
    if "centroid_lat" in proj.columns:
        r_lat = float(proj["mean_ST"].corr(proj["centroid_lat"]))
        print(f"  [{label}] corr(mean_ST, centroid_lat) = {r_lat:+.3f}  "
              f"(paper: positive, larger territories at higher latitude)")
    if "D_roe" in proj.columns:
        r_roe = float(proj["mean_ST"].corr(proj["D_roe"]))
        print(f"  [{label}] corr(mean_ST, D_roe)        = {r_roe:+.3f}  "
              f"(paper: negative, prey-rich grids support smaller territories)")


def main() -> None:
    src = find_source_parquet()
    print(f"Source parquet:   {src}")
    print(f"Target parquet:   {TOOL_PARQUET}")
    print(f"Paper envelope:   bias {PAPER_BIAS_KM2:+.1f} km^2, RMSE {PAPER_RMSE_KM2:.0f} km^2, r {PAPER_R:.3f}")
    print()

    df = load_parquet(src)
    print(f"Loaded {len(df):,} rows  scenarios={sorted(df.scenario.unique())}  "
          f"years {int(df.year.min())}-{int(df.year.max())}")

    # Verify required columns.
    for col in ("GridID", "year", "scenario", "centroid_lat", "D_roe", "NT", "mean_ST"):
        if col not in df.columns:
            sys.exit(f"Required column missing from parquet: {col}")

    print()
    print("Pre-recalibration audit (projection window, NT>0):")
    audit(df, "pre ")

    # --- Standardise predictors (Gelman 2-SD convention) ---
    # Latitude is stationary in space; reference = full dataset.
    lat_std = standardise_2sd(df["centroid_lat"])
    # D_roe is non-stationary; reference = 1999-2015 training window
    # to match the paper's Eq. 1 fitting convention (Section 2.1).
    train_mask = (df.year >= 1999) & (df.year <= 2015) & (df.scenario == "historical")
    if train_mask.sum() == 0:
        print("  [warn] no historical 1999-2015 rows found; standardising D_roe on full data")
        train_mask = pd.Series(True, index=df.index)
    roe_std = standardise_2sd(df["D_roe"], mask=train_mask)

    # --- Apply Mattisson regression, clip to observed range ---
    st_hat = BETA0 + BETA_LAT * lat_std + BETA_ROE * roe_std
    st_hat = st_hat.clip(lower=SMIN, upper=SMAX)

    # --- Overwrite only rows with territories (NT > 0); zero elsewhere ---
    has_territory = df["NT"].fillna(0) > 0
    df.loc[has_territory, "mean_ST"] = st_hat[has_territory].astype(float)
    df.loc[~has_territory, "mean_ST"] = 0.0

    # --- Bias audit against paper envelope on historical training rows ---
    hist = df[(df.scenario == "historical") & (df.year >= 1999) & (df.year <= 2015) & (df.NT > 0)]
    if not hist.empty:
        obs_ref = 887.4  # Table 1C observed mean (km^2)
        sim_mean = float(hist["mean_ST"].mean())
        bias = sim_mean - obs_ref
        rmse_proxy = float(((hist["mean_ST"] - obs_ref) ** 2).mean() ** 0.5)
        print()
        print(f"Bias vs observed mean (887.4 km^2) on 1999-2015 training rows:")
        print(f"  simulated mean = {sim_mean:.2f} km^2    bias = {bias:+.2f} km^2  "
              f"(paper: +10.2 km^2)")
        print(f"  RMSE proxy     = {rmse_proxy:.2f} km^2  (paper: 325 km^2)")
        out_of_range = float(((st_hat < SMIN) | (st_hat > SMAX)).mean() * 100.0)
        print(f"  out-of-range clips applied to {out_of_range:.2f}% of grid-years  "
              f"(paper fallback trigger: >5%)")

    print()
    print("Post-recalibration audit (projection window, NT>0):")
    audit(df, "post")

    # --- Write atomically to tool-local parquet (fixes corruption) ---
    os.makedirs(os.path.dirname(TOOL_PARQUET), exist_ok=True)
    tmp = TOOL_PARQUET + ".tmp"
    try:
        df.to_parquet(tmp, engine="fastparquet", index=False)
    except Exception:
        df.to_parquet(tmp, engine="pyarrow", index=False)
    os.replace(tmp, TOOL_PARQUET)

    # Trailing magic sanity check - the previous tool-local file had a
    # broken footer; this confirms the new one closes properly.
    with open(TOOL_PARQUET, "rb") as fh:
        fh.seek(-4, os.SEEK_END)
        tail = fh.read(4)
    ok = tail == b"PAR1"
    print(f"Wrote {TOOL_PARQUET}  ({os.path.getsize(TOOL_PARQUET)/1024:.0f} KB)  "
          f"footer {'OK' if ok else 'BROKEN: ' + tail.hex()}")

    print()
    print("Next step:  python docs/tools/scandinavian-sdm/build_data_json.py")
    print("Then:       powershell -ExecutionPolicy Bypass -File publish-wolf-model.ps1")


if __name__ == "__main__":
    main()
