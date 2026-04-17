# Deployment — Research Tools hub (Wolf-model repository)

This `docs/` directory is the GitHub Pages source for the *Research Tools*
hub that belongs to the `gsinchanpostdoc/Wolf-model` repository. The hub is
published at:

```
https://gsinchanpostdoc.github.io/Wolf-model/
```

and is linked to from the personal website at
`https://gsinchanpostdoc.github.io/Profile/`.

## Publish architecture

The tool is published from the Wolf-model repository, not the Profile
repository, because:

1. The 1.6 MB parquet and model code live with the model itself, keeping
   the personal-site repository small and its update cycle independent.
2. Citations resolve to a stable, model-attributed URL.
3. Regenerating the dataset updates only one repository.

The Profile site features a Research Tools card that links out to this hub.

## One-time GitHub Pages setup (Wolf-model repo)

1. Push the contents of this `Wolfapp/` folder to `gsinchanpostdoc/Wolf-model`
   on `main`. The exact command sequence is printed in the root
   `README.md` section titled *Publishing the tool site*.
2. In the repository, open **Settings → Pages**.
3. Under **Build and deployment**, set:
   - **Source:** *Deploy from a branch*
   - **Branch:** `main`
   - **Folder:** `/docs`
4. Save. GitHub Pages rebuilds on each push and typically publishes the hub
   at `https://gsinchanpostdoc.github.io/Wolf-model/` within a minute.

## Directory layout (published paths)

```
docs/
  index.html                       Research Tools landing page
  assets/style.css                 Shared site styling
  DEPLOYMENT.md                    (this file — not linked from the site)
  tools/
    scandinavian-sdm/
      index.html                   stlite wrapper + loader
      wolf_map.py                  Streamlit app (stlite build)
      data/
        map_data.parquet           Model outputs, 374 grids, 1999-2060
```

The stlite wrapper at `tools/scandinavian-sdm/index.html` loads
`wolf_map.py` and `data/map_data.parquet` via relative URLs, so the layout
above must be preserved on publish.

## stlite runtime contract

The wrapper declares these Pyodide packages (pinned for reproducibility):

```
folium==0.17.0
branca==0.7.2
plotly==5.22.0
pyarrow==16.1.0
```

`streamlit-folium` is intentionally **not** included — it ships custom JS
components that are not available in stlite. The stlite build of
`wolf_map.py` renders folium via `streamlit.components.v1.html(...)` and
uses a manual Grid ID selectbox instead of click-to-select.

## Post-publish smoke test

1. Open `https://gsinchanpostdoc.github.io/Wolf-model/` in a clean browser
   tab.
2. Click **Open the tool →** on the Scandinavian Species Distribution
   Models card. First load should take 20–40 seconds (Python + packages
   bootstrap once, then are cached).
3. Verify:
   - Sidebar shows Species, Variable, Scenario (five SSPs only), Year (2025–2060).
   - Map draws a colored grid over Scandinavia.
   - Scrolling down reveals a Grid ID selectbox and three time-series
     panels with historical (solid) + SSP (dashed) traces spanning
     1999–2060.

## Cross-linking from the Profile personal site

Add a card to `gsinchanpostdoc/Profile`'s landing page that points to this
hub. A drop-in HTML snippet (`tool_card_snippet.html`) is provided in the
repository root of Wolf-model.

## Updating model outputs

1. Regenerate the canonical parquet with the source pipeline
   (`src/app/build_map_data.py`).
2. Drop any grids whose `pred_*_density` columns contain NaN, to keep the
   hosted dataset uniform (this excludes 57 mostly-Svalbard grids).
3. Copy the refreshed file to
   `docs/tools/scandinavian-sdm/data/map_data.parquet`.
4. Bump the `v2.0` tag in `tools/scandinavian-sdm/index.html` and in the
   citation block of `docs/index.html`.
5. Push to `main`. GitHub Pages re-serves within a minute.

## Local preview

From this directory:

```bash
python -m http.server 8080
# open http://localhost:8080/
```

The stlite runtime fetches model files via HTTP, so the tool page will not
load when opened as a `file://` URL — always serve through a local HTTP
server for local previews.

## Citation

```
Ghosh, S. (2026). Scandinavian Species Distribution Models v2.0
  [Interactive research tool]. Wolf-model repository, IIASA postdoctoral
  research. Retrieved from
  https://gsinchanpostdoc.github.io/Wolf-model/tools/scandinavian-sdm/
```
