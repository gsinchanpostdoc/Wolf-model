# Wolf-model

Wolf–deer–ungulate system models with interactive density visualisations for
Scandinavia. IIASA postdoctoral research — Dr. Sinchan Ghosh.

The repository ships (1) the Streamlit application and pre-computed
simulation outputs that underpin the interactive map, and (2) a
browser-hosted build of that same application published through GitHub
Pages for foresters, game hunters, and wildlife managers.

## Interactive tool (stakeholder-facing)

**Live URL:** https://gsinchanpostdoc.github.io/Wolf-model/tools/scandinavian-sdm/

The hub page linking to the tool (and describing methods and citation) is
at https://gsinchanpostdoc.github.io/Wolf-model/, and is referenced from
the personal site at https://gsinchanpostdoc.github.io/Profile/ via the
drop-in card in `tool_card_snippet.html`.

### What the tool does

The tool renders grid-level density and habitat projections for wolves,
roe deer, and moose across 374 Scandinavian grid cells under five IPCC
Shared Socioeconomic Pathways (SSP1-1.9, SSP1-2.6, SSP2-4.5, SSP3-7.0,
SSP5-8.5) for the period 2025–2060. Per-grid time-series charts retain the
full 1999–2060 record (historical + projection) so stakeholders can see
projections against baseline variability.

## Desktop (developer / modeller) usage

Install dependencies and launch the full Streamlit application locally:

```bash
pip install -r requirements.txt
python run.py
# opens http://localhost:8501
```

| Requirement | Version |
|---|---|
| Python | 3.9 or later |
| OS | Windows, macOS, or Linux |

## Repository layout

```
Wolfapp/
  app/wolf_map.py              Desktop Streamlit app (uses streamlit-folium)
  data/map_data.parquet        Full simulation outputs (431 grids, 1999-2060)
  docs/                        GitHub Pages source (Research Tools hub)
    index.html                 Landing page
    assets/style.css           Styling
    DEPLOYMENT.md              Pages deployment steps
    USER_GUIDE.md              Full user guide
    screenshots/               Annotated screenshots
    tools/scandinavian-sdm/
      index.html               stlite wrapper + loader
      wolf_map.py              Browser build (no streamlit-folium)
      data/map_data.parquet    Cleaned subset (374 grids, no NaN)
  requirements.txt             Desktop Python dependencies
  run.py / run.sh / run.bat    Cross-platform launchers
  tool_card_snippet.html       Drop-in tile for the Profile personal site
  README.md                    (this file)
```

The desktop app and the browser build intentionally share scientific logic
but diverge on the map-rendering layer, because `streamlit-folium` is not
available in Pyodide. The browser build renders folium via
`streamlit.components.v1.html(...)` and uses a manual Grid ID selectbox.

## Publishing the tool site

GitHub Pages serves the `docs/` folder on `main`:

```bash
# From the Wolfapp/ root, one-time setup
git init
git add .
git commit -m "Initial publish: Scandinavian SDM v2.0"
git branch -M main
git remote add origin https://github.com/gsinchanpostdoc/Wolf-model.git
git push -u origin main
```

Then in the repository, open **Settings → Pages**, set:

- **Source:** *Deploy from a branch*
- **Branch:** `main`
- **Folder:** `/docs`

GitHub Pages rebuilds on each push and publishes within a minute. Full
details and smoke-test steps are in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Surfacing the tool on the Profile site

The file `tool_card_snippet.html` contains a styled tile (inline styles,
no external CSS dependencies) that links out to the tool. Paste the block
into the content area of `gsinchanpostdoc/Profile`'s `index.html`, commit,
and push.

## Data

`data/map_data.parquet` is the canonical simulation output (431 grids ×
62 years × 6 scenarios, 19 variables). The hosted build excludes 57 grids
whose predicted-density columns contain NaN — mostly Svalbard cells that
lie outside the current ecological range of Scandinavian wolves (Wabakken
et al., 2001). Excluded grids are reproducible by filtering
`pred_*_density` for NaN.

## Citation

```
Ghosh, S. (2026). Scandinavian Species Distribution Models v2.0
  [Interactive research tool]. Wolf-model repository, IIASA postdoctoral
  research. Retrieved from
  https://gsinchanpostdoc.github.io/Wolf-model/tools/scandinavian-sdm/
```

## Key references

Araújo MB & Guisan A (2006). Five (or so) challenges for species
distribution modelling. *J. Biogeogr.* 33, 1677–1688.

Chapron G et al. (2016). Estimating wolf population size and trend in
Scandinavia. *J. Wildl. Manage.*

Guisan A & Thuiller W (2005). Predicting species distribution: offering
more than simple habitat models. *Ecol. Lett.* 8, 993–1009.

IPCC AR6 WGI (2021). *Climate Change 2021: The Physical Science Basis.*

Riahi K et al. (2017). The Shared Socioeconomic Pathways and their
energy, land use, and greenhouse gas emissions implications. *Glob.
Environ. Change* 42, 153–168.

Wabakken P et al. (2001). The recovery, distribution, and population
dynamics of wolves on the Scandinavian peninsula, 1978–1998. *Can. J.
Zool.* 79, 710–725.

## License

Research and management use. No warranty of fitness for a particular
purpose.
