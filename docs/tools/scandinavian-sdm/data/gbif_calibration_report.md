# GBIF calibration report

Run window: training 1999-2015, projection 2016-2060.
Sources: GBIF occurrences (NO, SE), 141,447 rows after filters.

## Sample sizes

| species | kept records | grids with >= 5 overlap years |
|---|---|---|
| Canis lupus (wolf)        | 11,514 | 32 / 431 |
| Capreolus capreolus (roe) | 88,028 | 171 / 431 |
| Alces alces (moose)       | 41,905 | 192 / 431 |

## Temporal Spearman rho (1999-2015, per-grid, model vs GBIF)

| target | median rho | % grids rho > 0 | grids calibrated (rho > 0) |
|---|---|---|---|
| D_roe vs gbif_D_roe         | -0.071 | 46.2% | 79 |
| D_moose vs gbif_D_moose     | -0.035 | 44.8% | 86 |
| H vs gbif_D_wolf            | +0.076 | 62.5% | 20 |

## Spatial cross-sectional rho (per year, across grids)

This diagnostic is more informative than the temporal rho when
per-grid time series are short or noisy (Beale & Lennon, 2012).

| target | n_years | mean rho | min rho | max rho |
|---|---|---|---|---|
| D_roe vs gbif_D_roe   | 17 | +0.149 | -0.172 | +0.383 |
| D_moose vs gbif_D_moose | 17 | +0.150 | -0.094 | +0.334 |
| H vs gbif_D_wolf      | 14 | -0.037 | -0.514 | +0.245 |

## Pre- vs post-calibration mean / std on projection rows

Original columns:
stat  D_roe   D_moose  pred_roe_density  pred_moose_density  H     
----  ------  -------  ----------------  ------------------  ------
mean  0.1155  0.1593   0.0895            0.1436              0.2527
std   0.0515  0.0455   0.1411            0.1511              0.0511

Calibrated columns:
stat  D_roe_cal  D_moose_cal  pred_roe_density_cal  pred_moose_density_cal  H_cal 
----  ---------  -----------  --------------------  ----------------------  ------
mean  0.1252     0.1622       0.0992                0.1464                  0.2541
std   0.0629     0.0561       0.1409                0.1469                  0.0514


## Method

Per-grid shift: `shift(g) = mean(gbif_D_s, 1999-2015) - mean(D_s_model, 1999-2015)`.
Applied as `D_s_cal(g, t) = clip( D_s_model(g, t) + w(g) * shift(g), 0, 1 )`
with `w(g) = clip(rho_s(g), 0, 0.5)`. Maximum GBIF influence is
50%; historical rows and grids with rho <= 0 or n < 5
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
