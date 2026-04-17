"""
Scandinavian Species Distribution Models — browser-hosted Streamlit app.

This is the stlite / Pyodide build of the Wolf-Prey Ecosystem Explorer.
It renders in-browser with no server-side Python. Two adaptations from the
desktop version:

1. The interactive map uses folium rendered via streamlit.components.v1.html,
   because streamlit-folium is not available in Pyodide.
2. The map year range is restricted to 2025-2060 (projections only) per
   stakeholder request, while the per-grid time-series charts retain the
   full 1999-2060 historical + projection range for baseline context.

Intended audience: foresters, game hunters, and wildlife managers.
"""

import os
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
import branca.colormap as cm
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "map_data.parquet",
)

# Map controls only expose SSP projections (historical ends in 2015, outside
# the stakeholder-facing 2025+ scope). The time-series panel still renders
# historical traces for baseline context.
MAP_SCENARIO_MAP = {
    "SSP1-1.9 (strong mitigation)": "ssp119",
    "SSP1-2.6 (sustainability)": "ssp126",
    "SSP2-4.5 (middle of the road)": "ssp245",
    "SSP3-7.0 (regional rivalry)": "ssp370",
    "SSP5-8.5 (fossil-fuelled)": "ssp585",
}

# Full scenario list for the time-series panel.
TS_SCENARIO_MAP = {
    "Historical (1999-2015)": "historical",
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

SPECIES_PALETTES = {
    "Wolf": ["#ffffb2", "#fd8d3c", "#bd0026"],
    "Roe Deer": ["#f7fcf5", "#74c476", "#00441b"],
    "Moose": ["#f2f0f7", "#9e9ac8", "#4a1486"],
}


@st.cache_data
def load_data() -> pd.DataFrame:
    return pd.read_parquet(DATA_PATH, engine="fastparquet")


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Scandinavian SDM Explorer", layout="wide")
st.title("Scandinavian Species Distribution Models")
st.caption(
    "Wolf, roe deer, and moose density and habitat projections across Scandinavia — "
    "maps restricted to 2025-2060 projections; per-grid time series show the full "
    "1999-2060 record. Intended for foresters, game hunters, and wildlife managers."
)

df = load_data()

# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

st.sidebar.header("Map controls")

species = st.sidebar.selectbox("Species", list(SPECIES_VARIABLES.keys()))

var_options = SPECIES_VARIABLES[species]
var_label = st.sidebar.selectbox("Variable", list(var_options.keys()))
var_col = var_options[var_label]

scenario_label = st.sidebar.selectbox("Scenario", list(MAP_SCENARIO_MAP.keys()))
scenario_key = MAP_SCENARIO_MAP[scenario_label]

year_min, year_max = 2025, 2060
year = st.sidebar.slider("Year", min_value=year_min, max_value=year_max, value=year_min)

st.sidebar.markdown("---")
st.sidebar.caption(
    "Projections follow ISIMIP-bias-corrected CMIP6 forcings for the five SSP pathways "
    "(Riahi et al., 2017; IPCC AR6 WGI, 2021). Read outputs as directional under scenario "
    "uncertainty, not as precise counts."
)

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
    colors=SPECIES_PALETTES[species],
    vmin=vmin,
    vmax=vmax,
    caption=var_label,
)

for _, row in map_df.iterrows():
    val = row[var_col]
    ratio = (val - vmin) / (vmax - vmin) if vmax > vmin else 0.5
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
# Render map (static HTML — stlite-safe)
# ---------------------------------------------------------------------------

st.subheader(f"{var_label} — {scenario_label} ({year})")

components.html(m._repr_html_(), height=720, scrolling=False)

# ---------------------------------------------------------------------------
# Grid selection for time series
# ---------------------------------------------------------------------------

st.markdown("---")
st.header("Per-grid time series (1999-2060)")

st.caption(
    "Select a Grid ID to inspect its full historical record (1999-2015) alongside "
    "projections across all five SSP scenarios (2016-2060)."
)

grid_ids = sorted(df["GridID"].unique())

# Build nicer labels "ID — county, country" for the selectbox
meta = (
    df[["GridID", "county", "country"]]
    .drop_duplicates("GridID")
    .set_index("GridID")
    .to_dict(orient="index")
)

def _fmt_grid(gid: int) -> str:
    m = meta.get(gid, {})
    return f"{gid} — {m.get('county', '?')}, {m.get('country', '?')}"

grid_id = st.selectbox("Grid ID", grid_ids, format_func=_fmt_grid)

grid_meta = df.loc[df["GridID"] == grid_id, ["county", "country"]].iloc[0]
st.subheader(f"Grid {grid_id} ({grid_meta['county']}, {grid_meta['country']})")

# ---------------------------------------------------------------------------
# Time series charts (full 1999-2060)
# ---------------------------------------------------------------------------

grid_df = df[df["GridID"] == grid_id].copy()

WOLF_VARS = [
    ("WD", "Wolf Density"),
    ("WP_total", "Pack Size"),
    ("NT", "Territory Number"),
    ("mean_ST", "Territory Size"),
]
DEER_VARS = [
    ("D_roe", "Roe Deer Density"),
    ("D_moose", "Moose Density"),
    ("H", "Habitat Suitability"),
]
PRED_VARS = [
    ("pred_wolf_density", "Predicted Wolf Density"),
    ("pred_roe_density", "Predicted Roe Deer Density"),
    ("pred_moose_density", "Predicted Moose Density"),
]

CHART_GROUPS = [
    ("Wolf dynamics", WOLF_VARS),
    ("Prey density & habitat", DEER_VARS),
    ("Model-predicted densities", PRED_VARS),
]

for group_name, variables in CHART_GROUPS:
    st.markdown(f"#### {group_name}")
    cols = st.columns(len(variables))

    for i, (col_name, label) in enumerate(variables):
        fig = go.Figure()

        # Historical (solid)
        hist = grid_df[grid_df["scenario"] == "historical"].sort_values("year")
        if not hist.empty and col_name in hist.columns:
            fig.add_trace(go.Scatter(
                x=hist["year"], y=hist[col_name],
                mode="lines", name="Historical",
                line=dict(color=SCENARIO_COLORS["historical"], width=2),
            ))

        # SSP projections (dashed)
        for scen_label, scen_key in TS_SCENARIO_MAP.items():
            if scen_key == "historical":
                continue
            proj = grid_df[grid_df["scenario"] == scen_key].sort_values("year")
            if proj.empty or col_name not in proj.columns:
                continue
            fig.add_trace(go.Scatter(
                x=proj["year"], y=proj[col_name],
                mode="lines", name=scen_label.replace("SSP", "SSP "),
                line=dict(color=SCENARIO_COLORS[scen_key], width=1.5, dash="dash"),
            ))

        fig.add_vline(x=2015, line_dash="dot", line_color="gray",
                      annotation_text="Historical → Projection")
        fig.add_vline(x=2025, line_dash="dot", line_color="#1f3a2e",
                      annotation_text="Map window begins")

        fig.update_layout(
            title=label,
            xaxis_title="Year",
            yaxis_title=label,
            height=360,
            margin=dict(l=40, r=20, t=50, b=40),
            legend=dict(font=dict(size=9), orientation="h",
                        yanchor="bottom", y=-0.4),
        )

        with cols[i]:
            st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.caption(
    "Data: 374 Scandinavian grid cells (Norway + Sweden) on a ~50 km lattice. "
    "Svalbard and edge-case cells with incomplete prediction coverage have been "
    "excluded. Model version v2.0. Runs entirely in your browser via stlite / Pyodide; "
    "no data leaves your device."
)
