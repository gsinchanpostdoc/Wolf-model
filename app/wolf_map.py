"""
Scandinavian Wolf-Prey Ecosystem Explorer — Streamlit interactive map application.

Provides a choropleth map view of wolf, roe deer, and moose variables across
Scandinavian grid cells, plus per-grid time series charts spanning historical
(1999-2015) and SSP projection (2016-2060) periods.
"""

import os
import numpy as np
import pandas as pd
import streamlit as st
import folium
import branca.colormap as cm
import plotly.graph_objects as go
from streamlit_folium import st_folium

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "map_data.parquet")

SCENARIO_MAP = {
    "Historical": "historical",
    "SSP1-1.9": "ssp119",
    "SSP1-2.6": "ssp126",
    "SSP2-4.5": "ssp245",
    "SSP3-7.0": "ssp370",
    "SSP5-8.5": "ssp585",
}

SCENARIO_COLORS = {
    "historical": "#333333",
    "ssp119": "#1b9e77",
    "ssp126": "#66a61e",
    "ssp245": "#e6ab02",
    "ssp370": "#e7298a",
    "ssp585": "#d95f02",
}

SPECIES_VARIABLES = {
    "Wolf": {
        "Wolf Density (WD)": "WD",
        "Pack Size (WP_total)": "WP_total",
        "Territory Number (NT)": "NT",
        "Territory Size (mean_ST)": "mean_ST",
        "Solitary Wolves (W_solitary)": "W_solitary",
        "Predicted Wolf Density": "pred_wolf_density",
    },
    "Roe Deer": {
        "Deer Density (D_roe)": "D_roe",
        "Habitat Suitability (H)": "H",
        "Predicted Roe Deer Density": "pred_roe_density",
    },
    "Moose": {
        "Moose Density (D_moose)": "D_moose",
        "Habitat Suitability (H)": "H",
        "Predicted Moose Density": "pred_moose_density",
    },
}

COLORMAPS = {
    "Wolf": "YlOrRd",
    "Roe Deer": "Greens",
    "Moose": "BuPu",
}


@st.cache_data
def load_data() -> pd.DataFrame:
    return pd.read_parquet(DATA_PATH)


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Wolf-Prey Ecosystem Explorer", layout="wide")
st.title("Scandinavian Wolf-Prey Ecosystem Explorer")

df = load_data()

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

st.sidebar.header("Map Controls")

species = st.sidebar.selectbox("Species", list(SPECIES_VARIABLES.keys()))

var_options = SPECIES_VARIABLES[species]
var_label = st.sidebar.selectbox("Variable", list(var_options.keys()))
var_col = var_options[var_label]

scenario_label = st.sidebar.selectbox("Scenario", list(SCENARIO_MAP.keys()))
scenario_key = SCENARIO_MAP[scenario_label]

if scenario_key == "historical":
    year_min, year_max = 1999, 2015
else:
    year_min, year_max = 2016, 2060

year = st.sidebar.slider("Year", min_value=year_min, max_value=year_max, value=year_min)

# ---------------------------------------------------------------------------
# Filter data for the map
# ---------------------------------------------------------------------------

mask = (df["scenario"] == scenario_key) & (df["year"] == year)
map_df = df.loc[mask].copy()
map_df[var_col] = map_df[var_col].fillna(0)

# ---------------------------------------------------------------------------
# Build Folium map
# ---------------------------------------------------------------------------

m = folium.Map(location=[63.0, 15.0], zoom_start=5, tiles="CartoDB positron")

values = map_df[var_col]
vmin = float(values.min())
vmax = float(values.max())
if vmax <= vmin:
    vmax = vmin + 1.0

colormap = cm.LinearColormap(
    colors=["#ffffb2", "#fd8d3c", "#bd0026"] if species == "Wolf"
    else (["#f7fcf5", "#74c476", "#00441b"] if species == "Roe Deer"
          else ["#f2f0f7", "#9e9ac8", "#4a1486"]),
    vmin=vmin,
    vmax=vmax,
    caption=var_label,
)

for _, row in map_df.iterrows():
    val = row[var_col]
    # Scale radius between 3 and 15
    if vmax > vmin:
        ratio = (val - vmin) / (vmax - vmin)
    else:
        ratio = 0.5
    radius = 3 + ratio * 12

    folium.CircleMarker(
        location=[row["centroid_lat"], row["centroid_lon"]],
        radius=radius,
        color=colormap(val),
        fill=True,
        fill_color=colormap(val),
        fill_opacity=0.7,
        weight=1,
        tooltip=(
            f"Grid {int(row['GridID'])} | {row['county']}, {row['country']}<br>"
            f"{var_label}: {val:.4g}<br>"
            f"Year: {int(row['year'])}"
        ),
    ).add_to(m)

colormap.add_to(m)

# ---------------------------------------------------------------------------
# Render map
# ---------------------------------------------------------------------------

st.subheader(f"{var_label} — {scenario_label} ({year})")

map_data = st_folium(m, width=None, height=700, returned_objects=["last_object_clicked"])

# ---------------------------------------------------------------------------
# Grid selection for time series
# ---------------------------------------------------------------------------

st.markdown("---")
st.header("Grid Time Series")

col_click, col_manual = st.columns(2)

clicked_grid = None
if map_data and map_data.get("last_object_clicked"):
    click_lat = map_data["last_object_clicked"].get("lat")
    click_lng = map_data["last_object_clicked"].get("lng")
    if click_lat is not None and click_lng is not None:
        # Find the nearest grid
        dists = (map_df["centroid_lat"] - click_lat) ** 2 + (map_df["centroid_lon"] - click_lng) ** 2
        if len(dists) > 0:
            clicked_grid = int(map_df.loc[dists.idxmin(), "GridID"])

with col_click:
    if clicked_grid is not None:
        st.info(f"Clicked grid: **{clicked_grid}**")
    else:
        st.info("Click a marker on the map to select a grid.")

with col_manual:
    grid_ids = sorted(df["GridID"].unique())
    default_idx = grid_ids.index(clicked_grid) if clicked_grid in grid_ids else 0
    selected_grid = st.selectbox("Or select Grid ID manually", grid_ids, index=default_idx)

grid_id = clicked_grid if clicked_grid is not None else selected_grid

# Grid metadata
grid_meta = df.loc[df["GridID"] == grid_id, ["county", "country"]].iloc[0]
st.subheader(f"Time Series for Grid {grid_id} ({grid_meta['county']}, {grid_meta['country']})")

# ---------------------------------------------------------------------------
# Time series charts
# ---------------------------------------------------------------------------

grid_df = df[df["GridID"] == grid_id].copy()

WOLF_VARS = [("WD", "Wolf Density"), ("WP_total", "Pack Size"),
             ("NT", "Territory Number"), ("mean_ST", "Territory Size")]
DEER_VARS = [("D_roe", "Roe Deer Density"), ("D_moose", "Moose Density"), ("H", "Habitat Suitability")]
PRED_VARS = [("pred_wolf_density", "Predicted Wolf Density"),
             ("pred_roe_density", "Predicted Roe Deer Density"),
             ("pred_moose_density", "Predicted Moose Density")]

CHART_GROUPS = [
    ("Wolf Variables", WOLF_VARS),
    ("Deer & Habitat Variables", DEER_VARS),
    ("Predicted Densities", PRED_VARS),
]

for group_name, variables in CHART_GROUPS:
    st.markdown(f"#### {group_name}")
    cols = st.columns(len(variables))

    for i, (col_name, label) in enumerate(variables):
        fig = go.Figure()

        # Historical
        hist = grid_df[grid_df["scenario"] == "historical"].sort_values("year")
        if not hist.empty and col_name in hist.columns:
            fig.add_trace(go.Scatter(
                x=hist["year"], y=hist[col_name],
                mode="lines", name="Historical",
                line=dict(color=SCENARIO_COLORS["historical"], width=2),
            ))

        # SSP projections
        for scen_label, scen_key in SCENARIO_MAP.items():
            if scen_key == "historical":
                continue
            proj = grid_df[grid_df["scenario"] == scen_key].sort_values("year")
            if proj.empty or col_name not in proj.columns:
                continue
            fig.add_trace(go.Scatter(
                x=proj["year"], y=proj[col_name],
                mode="lines", name=scen_label,
                line=dict(color=SCENARIO_COLORS[scen_key], width=1.5, dash="dash"),
            ))

        # Vertical boundary line at 2015
        fig.add_vline(x=2015, line_dash="dot", line_color="gray", annotation_text="2015")

        fig.update_layout(
            title=label,
            xaxis_title="Year",
            yaxis_title=label,
            height=350,
            margin=dict(l=40, r=20, t=40, b=40),
            legend=dict(font=dict(size=9), orientation="h", yanchor="bottom", y=-0.4),
        )

        with cols[i]:
            st.plotly_chart(fig, use_container_width=True)
