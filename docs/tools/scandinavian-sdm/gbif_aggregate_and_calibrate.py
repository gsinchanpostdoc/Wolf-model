"""
gbif_aggregate_and_calibrate.py
--------------------------------
Second stage of the GBIF validation pipeline.

Inputs
------
    data/gbif_occurrences.csv   (from gbif_download.py)
    data/map_data.parquet       (the tool's published data)

Outputs
-------
    data/gbif_grid_counts.csv        raw counts per (GridID, year, species)
    data/gbif_relative_indices.csv   per-source min-max-normalised indices
                                     on [0,1] (Eq. 1a mirror)
    data/gbif_agreement.csv          per-grid Spearman rho (model vs GBIF)
                                     over the 1999-2015 training window
    data/gbif_calibration_report.md  human-readable audit
    data/map_data.parquet            IN PLACE: adds calibrated columns
        D_roe_cal, D_moose_cal, pred_roe_density_cal, pred_moose_density_cal,
        H_cal, gbif_agreement (per-grid [-1, 1] summary)

Scientific approach
-------------------
This script implements Option 2 from the calibration plan:
independent-source overlay with weighted, bias-bounded calibration. The
model's spatial mechanism is preserved. GBIF shifts the projection only
where the 1999-2015 training window shows defensible per-grid agreement.

Concretely, for each species s in {roe, moose, wolf}:

    gbif_D_s(g, t) = clip( [ log(1+n_s(g,t)) - m_s ] / [ M_s - m_s ], 0, 1 )

    where m_s, M_s are the min/max of log(1+n_s(g,t)) over the
    1999-2015 training window. This mirrors Eq. 1a of Ghosh, Franklin &
    Zimmermann (2026). The log(1+n) transform tames citizen-science
    right-skew per Isaac et al. (2014) Methods Ecol. Evol. 5:1052-1060.

Per-grid agreement:
    rho_s(g) = Spearman( D_s_model(g, 1999..2015), gbif_D_s(g, 1999..2015) )

Per-grid calibration (projection rows, year >= 2016 only):
    w_s(g)     = clip(rho_s(g), 0, 0.5)          # cap at 50% influence
    shift_s(g) = mean(gbif_D_s(g, 1999..2015))
                 - mean(D_s_model(g, 1999..2015))
    D_s_cal(g, t) = clip( D_s_model(g, t) + w_s(g) * shift_s(g), 0, 1 )

Historical rows (scenario == 'historical') are never overwritten.
Grids with fewer than 5 overlapping years or non-positive rho get
calibrated == original model value (no blind trust of noisy citizen
data where the model already disagrees).

Caveat documented in the report: GBIF cannot distinguish moose calves
from adults, so D_moose_cal corrects spatial pattern only. Wolf
observations in GBIF partially overlap Rovbase (the model's training
source), so H_cal is flagged as confirmatory, not independent.

Author: Dr. Sinchan Ghosh (pipeline scaffolding by assistant), 2026.
"""
from __future__ import annotations

import os
import sys
import math
import json
from typing import Dict, Tuple, List

try:
    import numpy as np
    import pandas as pd
except ImportError:
    sys.exit("numpy and pandas are required. "
             "Install with: pip install pandas numpy scipy pyarrow")

try:
    from scipy.stats import spearmanr
except ImportError:
    sys.exit("scipy is required. Install with: pip install scipy")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
GBIF_CSV = os.path.join(DATA_DIR, "gbif_occurrences.csv")
PARQUET = os.path.join(DATA_DIR, "map_data.parquet")
COUNTS_CSV = os.path.join(DATA_DIR, "gbif_grid_counts.csv")
INDEX_CSV = os.path.join(DATA_DIR, "gbif_relative_indices.csv")
AGREE_CSV = os.path.join(DATA_DIR, "gbif_agreement.csv")
REPORT_MD = os.path.join(DATA_DIR, "gbif_calibration_report.md")

# Training window used by the paper for Eq. 1a normalisation.
TRAIN_YEARS = range(1999, 2016)   # inclusive of 2015

# Species mapping: GBIF species string -> (model_D, model_pred, short).
SPECIES_MAP = {
    "Capreolus capreolus": {"short": "roe",   "model_D": "D_roe",
                            "model_pred": "pred_roe_density"},
    "Alces alces":         {"short": "moose", "model_D": "D_moose",
                            "model_pred": "pred_moose_density"},
    "Canis lupus":         {"short": "wolf",  "model_D": "H",
                            "model_pred": None},
}

# Maximum acceptable distance from GBIF point to nearest grid centroid.
# Grid is 50 x 50 km; centroid-to-corner is sqrt(2)*25 ~= 35.4 km.
# 35 km keeps points inside the nominal cell footprint.
MAX_SNAP_KM = 35.0

# Coordinate uncertainty threshold: drop points whose reported uncertainty
# exceeds half a cell side (25 km). Missing values are treated as OK.
MAX_COORD_UNCERT_M = 25_000

# Maximum GBIF weight in the blended calibration. Capping at 0.5 preserves
# model primacy regardless of how strong the per-grid correlation is.
MAX_WEIGHT = 0.5

# Minimum number of training-window overlap years required to accept rho.
MIN_OVERLAP_YEARS = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lon1, lat2, lon2):
    """Haversine great-circle distance in km, vectorised for numpy arrays."""
    r = 6371.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load_parquet_tolerant(path: str) -> pd.DataFrame:
    try:
        return pd.read_parquet(path, engine="fastparquet")
    except Exception:
        return pd.read_parquet(path)


def write_parquet_tolerant(df: pd.DataFrame, path: str) -> None:
    tmp = path + ".tmp"
    try:
        df.to_parquet(tmp, engine="fastparquet", index=False)
    except Exception:
        df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Stage B -- grid aggregation
# ---------------------------------------------------------------------------

def aggregate_to_grid(gbif: pd.DataFrame, grids: pd.DataFrame) -> pd.DataFrame:
    """Snap every GBIF point to its nearest grid centroid and count per
    (GridID, year, species). Drop points farther than MAX_SNAP_KM or with
    coordinateUncertaintyInMeters > MAX_COORD_UNCERT_M."""
    # Coordinate-uncertainty filter (keep NaN as OK).
    if "coordinateUncertaintyInMeters" in gbif.columns:
        bad = gbif["coordinateUncertaintyInMeters"].fillna(0) > MAX_COORD_UNCERT_M
        n_bad = int(bad.sum())
        if n_bad:
            print(f"  dropping {n_bad:,} points with coord uncertainty > "
                  f"{MAX_COORD_UNCERT_M/1000:.0f} km")
            gbif = gbif[~bad]

    # Nearest-centroid snap (brute force; 374 grids x ~150k points fits
    # comfortably in memory).
    g_lat = grids["centroid_lat"].to_numpy(float)
    g_lon = grids["centroid_lon"].to_numpy(float)
    g_id = grids["GridID"].to_numpy(int)

    lat = gbif["decimalLatitude"].to_numpy(float)
    lon = gbif["decimalLongitude"].to_numpy(float)

    # Chunk the distance matrix to bound memory.
    CHUNK = 20_000
    snapped = np.empty(len(gbif), dtype=int)
    dists = np.empty(len(gbif), dtype=float)
    for i0 in range(0, len(gbif), CHUNK):
        i1 = min(i0 + CHUNK, len(gbif))
        dmat = _haversine_km(
            lat[i0:i1, None], lon[i0:i1, None],
            g_lat[None, :], g_lon[None, :]
        )
        j = dmat.argmin(axis=1)
        snapped[i0:i1] = g_id[j]
        dists[i0:i1] = dmat[np.arange(i1 - i0), j]

    out = gbif.assign(GridID=snapped, snap_km=dists)
    far = out["snap_km"] > MAX_SNAP_KM
    print(f"  dropping {int(far.sum()):,} points farther than "
          f"{MAX_SNAP_KM} km from any grid centroid")
    out = out[~far]

    counts = (out.groupby(["GridID", "year", "species"], dropna=False)
                 .size().rename("count").reset_index())
    return counts


# ---------------------------------------------------------------------------
# Stage C -- per-source relative index
# ---------------------------------------------------------------------------

def make_relative_indices(counts: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Tuple[float, float]]]:
    """Compute gbif_D_s on [0,1] per (GridID, year, species).

    Enhancement over plain min-max: before normalisation, remove the
    global per-year mean of log(1 + count) across all grids reporting
    the species in that year. This controls for the well-documented
    citizen-science observer-effort trend (platform growth, media
    events) that otherwise swamps the biological signal at the
    per-grid per-year level (Isaac et al., 2014, Methods Ecol. Evol.
    5:1052-1060; Kamp et al., 2016, Ecology 97:1878-1884).

    Pipeline:
        log_n = log(1 + count)
        log_n_detrend(g, t) = log_n(g, t) - mean_g( log_n(., t) )
        gbif_D(g, t) = clip( (log_n_detrend - m) / (M - m), 0, 1 )
    where m, M are the training-window (1999-2015) min/max of
    log_n_detrend across all grid-years of that species. The same
    training-window constants are applied to the projection window,
    mirroring Eq. 1a of Ghosh, Franklin & Zimmermann (2026).
    """
    counts = counts.copy()
    counts["log_n"] = np.log1p(counts["count"].astype(float))

    norm: Dict[str, Tuple[float, float]] = {}
    rows = []
    for species, meta in SPECIES_MAP.items():
        sub = counts[counts["species"] == species]
        if sub.empty:
            print(f"  [skip] no counts for {species}")
            continue
        # Global per-year mean across all grids reporting this species.
        yr_mean = sub.groupby("year")["log_n"].transform("mean")
        sub = sub.assign(log_n_detrend=sub["log_n"] - yr_mean)
        train = sub[sub["year"].between(min(TRAIN_YEARS), max(TRAIN_YEARS))]
        if train.empty:
            print(f"  [warn] no training-window counts for {species}; "
                  f"falling back to full-range min/max")
            train = sub
        m = float(train["log_n_detrend"].min())
        M = float(train["log_n_detrend"].max())
        if M <= m:
            print(f"  [warn] degenerate normalisation for {species} "
                  f"(min={m:.3f}, max={M:.3f}); emitting zeros")
            M = m + 1e-9
        norm[species] = (m, M)
        s = sub.copy()
        s["gbif_D"] = ((s["log_n_detrend"] - m) / (M - m)).clip(0.0, 1.0)
        s["short"] = meta["short"]
        rows.append(s[["GridID", "year", "short", "count", "gbif_D"]])

    long = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(
        columns=["GridID", "year", "short", "count", "gbif_D"])
    wide = long.pivot_table(index=["GridID", "year"],
                            columns="short",
                            values="gbif_D",
                            aggfunc="first").reset_index()
    wide = wide.rename(columns={"wolf":  "gbif_D_wolf",
                                "roe":   "gbif_D_roe",
                                "moose": "gbif_D_moose"})
    return wide, norm


# ---------------------------------------------------------------------------
# Stage D/E -- per-grid agreement and calibration
# ---------------------------------------------------------------------------

def per_grid_rho(model_df: pd.DataFrame, gbif_wide: pd.DataFrame,
                 model_col: str, gbif_col: str) -> pd.DataFrame:
    """Spearman rho per GridID over the training window (temporal).

    Answers: within this grid, does the model's year-to-year variation
    track GBIF's year-to-year variation? This is fragile in the face of
    citizen-science effort trends (partly mitigated by year-detrending
    in make_relative_indices).

    Returns DataFrame[GridID, rho, n]."""
    hist = model_df[(model_df["scenario"] == "historical")
                    & model_df["year"].between(min(TRAIN_YEARS), max(TRAIN_YEARS))]
    merged = hist.merge(gbif_wide[["GridID", "year", gbif_col]],
                        on=["GridID", "year"], how="left")
    merged = merged.dropna(subset=[model_col, gbif_col])

    rows = []
    for gid, grp in merged.groupby("GridID"):
        if len(grp) < MIN_OVERLAP_YEARS:
            continue
        if grp[model_col].nunique() < 2 or grp[gbif_col].nunique() < 2:
            continue
        rho, _ = spearmanr(grp[model_col], grp[gbif_col])
        if np.isnan(rho):
            continue
        rows.append({"GridID": gid, "rho": float(rho), "n": int(len(grp))})
    return pd.DataFrame(rows)


def spatial_rho_per_year(model_df: pd.DataFrame, gbif_wide: pd.DataFrame,
                         model_col: str, gbif_col: str) -> pd.DataFrame:
    """Spearman rho per year across grids (spatial cross-section).

    Answers: in a given year, does the spatial pattern of the model
    across grids match the spatial pattern of GBIF observations across
    grids? This is the scientifically informative metric when
    per-grid time series are short or noisy (Beale & Lennon, 2012,
    Phil. Trans. B 367:247-258).

    Returns DataFrame[year, rho, n_grids]."""
    hist = model_df[(model_df["scenario"] == "historical")
                    & model_df["year"].between(min(TRAIN_YEARS), max(TRAIN_YEARS))]
    merged = hist.merge(gbif_wide[["GridID", "year", gbif_col]],
                        on=["GridID", "year"], how="left")
    merged = merged.dropna(subset=[model_col, gbif_col])

    rows = []
    for yr, grp in merged.groupby("year"):
        if len(grp) < 10:
            continue
        if grp[model_col].nunique() < 2 or grp[gbif_col].nunique() < 2:
            continue
        rho, _ = spearmanr(grp[model_col], grp[gbif_col])
        if np.isnan(rho):
            continue
        rows.append({"year": int(yr), "rho": float(rho), "n_grids": int(len(grp))})
    return pd.DataFrame(rows)


def _fmt_stats_block(df: pd.DataFrame, title: str) -> str:
    """Render a stats DataFrame as a plain-text table. No tabulate needed."""
    if df.empty:
        return f"{title}: (empty)\n"
    cols = list(df.columns)
    widths = {c: max(len(c), max((len(f"{v:.4f}" if isinstance(v, float) else str(v))
                                  for v in df[c]), default=0)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep = "  ".join("-" * widths[c] for c in cols)
    lines = [title, header, sep]
    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            cells.append((f"{v:.4f}" if isinstance(v, float) else str(v)).ljust(widths[c]))
        lines.append("  ".join(cells))
    return "\n".join(lines) + "\n"


def calibrate_column(model_df: pd.DataFrame, gbif_wide: pd.DataFrame,
                     model_col: str, gbif_col: str, cal_col: str,
                     rho_tbl: pd.DataFrame) -> pd.DataFrame:
    """Create cal_col = model_col shifted by per-grid bias, weighted by
    rho (capped at MAX_WEIGHT), for projection rows only. Historical
    rows and non-calibratable grids are copied through unchanged."""
    df = model_df.copy()
    df[cal_col] = df[model_col].astype(float)   # default = untouched

    # Per-grid shift from training-window means.
    hist = df[df["scenario"] == "historical"].merge(
        gbif_wide[["GridID", "year", gbif_col]],
        on=["GridID", "year"], how="left")
    hist = hist[hist["year"].between(min(TRAIN_YEARS), max(TRAIN_YEARS))]
    hist = hist.dropna(subset=[gbif_col, model_col])
    mean_model = hist.groupby("GridID")[model_col].mean()
    mean_gbif = hist.groupby("GridID")[gbif_col].mean()
    shift = (mean_gbif - mean_model).rename("shift").to_frame()

    w = rho_tbl.set_index("GridID")["rho"].clip(lower=0, upper=MAX_WEIGHT)
    w = w.rename("weight").to_frame()
    bias = shift.join(w, how="inner")
    bias["delta"] = bias["shift"] * bias["weight"]

    # Apply only to projection rows.
    proj_mask = df["scenario"] != "historical"
    deltas = df.loc[proj_mask, ["GridID"]].join(
        bias["delta"], on="GridID").fillna(0.0)["delta"].values
    df.loc[proj_mask, cal_col] = (df.loc[proj_mask, model_col].astype(float)
                                  + deltas).clip(0.0, 1.0)
    return df, bias


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not os.path.exists(GBIF_CSV):
        sys.exit(f"Missing {GBIF_CSV}. Run gbif_download.py first.")
    if not os.path.exists(PARQUET):
        sys.exit(f"Missing {PARQUET}.")

    print(f"Loading {GBIF_CSV} ...")
    gbif = pd.read_csv(GBIF_CSV)
    gbif = gbif.dropna(subset=["decimalLatitude", "decimalLongitude", "year"])
    gbif["year"] = gbif["year"].astype(int)
    print(f"  {len(gbif):,} rows; species: "
          f"{gbif['species'].value_counts().to_dict()}")

    print(f"Loading {PARQUET} ...")
    model_df = load_parquet_tolerant(PARQUET)
    print(f"  {len(model_df):,} rows, {model_df['GridID'].nunique()} grids, "
          f"years {int(model_df['year'].min())}-{int(model_df['year'].max())}")

    grids = (model_df[["GridID", "centroid_lat", "centroid_lon"]]
             .drop_duplicates("GridID").reset_index(drop=True))

    # Stage B -- aggregate.
    print("Aggregating GBIF points to grid cells ...")
    counts = aggregate_to_grid(gbif, grids)
    counts.to_csv(COUNTS_CSV, index=False)
    print(f"  wrote {COUNTS_CSV} ({len(counts):,} rows)")

    # Stage C -- relative indices.
    print("Computing per-species relative density indices ...")
    gbif_wide, norm = make_relative_indices(counts)
    gbif_wide.to_csv(INDEX_CSV, index=False)
    print(f"  wrote {INDEX_CSV} ({len(gbif_wide):,} rows)")
    for sp, (m, M) in norm.items():
        print(f"    {sp:22s}  log(1+n) min={m:.3f}  max={M:.3f}")

    # Stage D -- per-grid temporal rho.
    print("Per-grid temporal Spearman rho (1999-2015 training window) ...")
    rho_roe = per_grid_rho(model_df, gbif_wide, "D_roe",   "gbif_D_roe")
    rho_moo = per_grid_rho(model_df, gbif_wide, "D_moose", "gbif_D_moose")
    rho_wlf = per_grid_rho(model_df, gbif_wide, "H",       "gbif_D_wolf")
    print(f"  roe deer  : n_grids={len(rho_roe):3d}  "
          f"median rho={rho_roe['rho'].median() if len(rho_roe) else float('nan'):+.3f}  "
          f"pct rho>0 ={(rho_roe['rho']>0).mean()*100 if len(rho_roe) else float('nan'):5.1f}%")
    print(f"  moose     : n_grids={len(rho_moo):3d}  "
          f"median rho={rho_moo['rho'].median() if len(rho_moo) else float('nan'):+.3f}  "
          f"pct rho>0 ={(rho_moo['rho']>0).mean()*100 if len(rho_moo) else float('nan'):5.1f}%")
    print(f"  wolf (H)  : n_grids={len(rho_wlf):3d}  "
          f"median rho={rho_wlf['rho'].median() if len(rho_wlf) else float('nan'):+.3f}  "
          f"pct rho>0 ={(rho_wlf['rho']>0).mean()*100 if len(rho_wlf) else float('nan'):5.1f}%")

    # Spatial cross-section rho per year.
    print("Spatial cross-sectional rho per year (across grids) ...")
    sp_roe = spatial_rho_per_year(model_df, gbif_wide, "D_roe",   "gbif_D_roe")
    sp_moo = spatial_rho_per_year(model_df, gbif_wide, "D_moose", "gbif_D_moose")
    sp_wlf = spatial_rho_per_year(model_df, gbif_wide, "H",       "gbif_D_wolf")
    for lbl, sp in (("roe deer", sp_roe), ("moose", sp_moo), ("wolf (H)", sp_wlf)):
        if len(sp):
            print(f"  {lbl:9s}: n_years={len(sp):2d}  "
                  f"mean spatial rho={sp['rho'].mean():+.3f}  "
                  f"min={sp['rho'].min():+.3f}  max={sp['rho'].max():+.3f}")
        else:
            print(f"  {lbl:9s}: insufficient spatial coverage")

    agree = rho_roe.rename(columns={"rho": "rho_roe",  "n": "n_roe"}) \
        .merge(rho_moo.rename(columns={"rho": "rho_moose", "n": "n_moose"}),
               on="GridID", how="outer") \
        .merge(rho_wlf.rename(columns={"rho": "rho_wolf",  "n": "n_wolf"}),
               on="GridID", how="outer")
    agree.to_csv(AGREE_CSV, index=False)
    print(f"  wrote {AGREE_CSV} ({len(agree):,} rows)")

    # Stage E -- calibrate.
    print("Applying capped per-grid bias calibration to projection rows ...")
    pre_stats = model_df[model_df["scenario"] != "historical"][
        ["D_roe", "D_moose", "pred_roe_density", "pred_moose_density", "H"]
    ].describe().loc[["mean", "std"]]

    model_df, bias_roe = calibrate_column(
        model_df, gbif_wide, "D_roe",              "gbif_D_roe",   "D_roe_cal",              rho_roe)
    model_df, bias_roepred = calibrate_column(
        model_df, gbif_wide, "pred_roe_density",   "gbif_D_roe",   "pred_roe_density_cal",   rho_roe)
    model_df, bias_moo = calibrate_column(
        model_df, gbif_wide, "D_moose",            "gbif_D_moose", "D_moose_cal",            rho_moo)
    model_df, bias_moopred = calibrate_column(
        model_df, gbif_wide, "pred_moose_density", "gbif_D_moose", "pred_moose_density_cal", rho_moo)
    model_df, bias_wlf = calibrate_column(
        model_df, gbif_wide, "H",                  "gbif_D_wolf",  "H_cal",                  rho_wlf)

    # Per-grid summary agreement index: mean of available rhos, clipped [-1,1].
    g_agree = agree.set_index("GridID")[
        ["rho_roe", "rho_moose", "rho_wolf"]].mean(axis=1).rename("gbif_agreement")
    model_df = model_df.merge(g_agree, on="GridID", how="left")

    post_stats = model_df[model_df["scenario"] != "historical"][
        ["D_roe_cal", "D_moose_cal", "pred_roe_density_cal",
         "pred_moose_density_cal", "H_cal"]
    ].describe().loc[["mean", "std"]]

    write_parquet_tolerant(model_df, PARQUET)
    print(f"  wrote {PARQUET} ({os.path.getsize(PARQUET)/1024:.0f} KB)")

    # Report.
    n_cal_roe = int((rho_roe["rho"] > 0).sum()) if len(rho_roe) else 0
    n_cal_moo = int((rho_moo["rho"] > 0).sum()) if len(rho_moo) else 0
    n_cal_wlf = int((rho_wlf["rho"] > 0).sum()) if len(rho_wlf) else 0
    total_grids = int(model_df["GridID"].nunique())

    # Pre-compute plain-text stats blocks (no tabulate dependency).
    pre_tbl = pre_stats.round(4).reset_index().rename(columns={"index": "stat"})
    post_tbl = post_stats.round(4).reset_index().rename(columns={"index": "stat"})
    pre_block = _fmt_stats_block(pre_tbl, "Original columns:")
    post_block = _fmt_stats_block(post_tbl, "Calibrated columns:")
    report = f"""# GBIF calibration report

Run window: training 1999-2015, projection 2016-2060.
Sources: GBIF occurrences (NO, SE), {len(gbif):,} rows after filters.

## Sample sizes

| species | kept records | grids with >= {MIN_OVERLAP_YEARS} overlap years |
|---|---|---|
| Canis lupus (wolf)        | {(gbif['species']=='Canis lupus').sum():,} | {len(rho_wlf)} / {total_grids} |
| Capreolus capreolus (roe) | {(gbif['species']=='Capreolus capreolus').sum():,} | {len(rho_roe)} / {total_grids} |
| Alces alces (moose)       | {(gbif['species']=='Alces alces').sum():,} | {len(rho_moo)} / {total_grids} |

## Temporal Spearman rho (1999-2015, per-grid, model vs GBIF)

| target | median rho | % grids rho > 0 | grids calibrated (rho > 0) |
|---|---|---|---|
| D_roe vs gbif_D_roe         | {rho_roe['rho'].median() if len(rho_roe) else float('nan'):+.3f} | {(rho_roe['rho']>0).mean()*100 if len(rho_roe) else float('nan'):.1f}% | {n_cal_roe} |
| D_moose vs gbif_D_moose     | {rho_moo['rho'].median() if len(rho_moo) else float('nan'):+.3f} | {(rho_moo['rho']>0).mean()*100 if len(rho_moo) else float('nan'):.1f}% | {n_cal_moo} |
| H vs gbif_D_wolf            | {rho_wlf['rho'].median() if len(rho_wlf) else float('nan'):+.3f} | {(rho_wlf['rho']>0).mean()*100 if len(rho_wlf) else float('nan'):.1f}% | {n_cal_wlf} |

## Spatial cross-sectional rho (per year, across grids)

This diagnostic is more informative than the temporal rho when
per-grid time series are short or noisy (Beale & Lennon, 2012).

| target | n_years | mean rho | min rho | max rho |
|---|---|---|---|---|
| D_roe vs gbif_D_roe   | {len(sp_roe)} | {sp_roe['rho'].mean() if len(sp_roe) else float('nan'):+.3f} | {sp_roe['rho'].min() if len(sp_roe) else float('nan'):+.3f} | {sp_roe['rho'].max() if len(sp_roe) else float('nan'):+.3f} |
| D_moose vs gbif_D_moose | {len(sp_moo)} | {sp_moo['rho'].mean() if len(sp_moo) else float('nan'):+.3f} | {sp_moo['rho'].min() if len(sp_moo) else float('nan'):+.3f} | {sp_moo['rho'].max() if len(sp_moo) else float('nan'):+.3f} |
| H vs gbif_D_wolf      | {len(sp_wlf)} | {sp_wlf['rho'].mean() if len(sp_wlf) else float('nan'):+.3f} | {sp_wlf['rho'].min() if len(sp_wlf) else float('nan'):+.3f} | {sp_wlf['rho'].max() if len(sp_wlf) else float('nan'):+.3f} |

## Pre- vs post-calibration mean / std on projection rows

{pre_block}
{post_block}

## Method

Per-grid shift: `shift(g) = mean(gbif_D_s, 1999-2015) - mean(D_s_model, 1999-2015)`.
Applied as `D_s_cal(g, t) = clip( D_s_model(g, t) + w(g) * shift(g), 0, 1 )`
with `w(g) = clip(rho_s(g), 0, {MAX_WEIGHT})`. Maximum GBIF influence is
{int(MAX_WEIGHT*100)}%; historical rows and grids with rho <= 0 or n < {MIN_OVERLAP_YEARS}
years are passed through unchanged.

## Caveats

- Moose: GBIF cannot distinguish calves from adults. `D_moose_cal`
  therefore reflects spatial-pattern correction only. Magnitude
  disagreement between model (calves-only) and GBIF (all ages) is
  expected and is absorbed by the per-grid shift rather than a global
  rescaling.
- Wolf: GBIF wolf records partially mirror Rovbase, which is already in
  the model's training set. `H_cal` is confirmatory, not independent.
- Citizen-science effort bias is partially neutralised by the
  min-max-normalised log(1+n) transform (Isaac et al. 2014). Grids with
  zero observations in the training window are not calibratable and
  keep the model's own value.
"""
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  wrote {REPORT_MD}")
    print()
    print("Done. Next: python build_data_json.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
