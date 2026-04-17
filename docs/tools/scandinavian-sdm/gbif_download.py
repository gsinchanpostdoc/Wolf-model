"""
gbif_download.py
-----------------
Pull GBIF occurrence records for Canis lupus, Capreolus capreolus, and
Alces alces over Norway + Sweden, 1999-2024, for validation of the
Scandinavian wolf/roe/moose SDM tool.

Output: data/gbif_occurrences.csv with columns
    gbifID, species, taxonKey, decimalLatitude, decimalLongitude,
    year, country, datasetKey, basisOfRecord,
    coordinateUncertaintyInMeters

IMPORTANT (scientific):
- Rovbase is the authoritative wolf ground-truth ALREADY IN the model's
  training set, so GBIF is treated as an INDEPENDENT validator, not a
  training source. Re-blending would double-count.
- GBIF effort is biased toward roads/protected areas. Downstream
  aggregation uses a log(1+count) transform (Isaac et al. 2014, MEE) and
  per-database relative indexing to tame that bias.
- Moose in the SDM means CALVES only (Alces alces). GBIF cannot
  distinguish calves vs adults, so it validates SPATIAL PATTERN only.

Author: Dr. Sinchan Ghosh (pipeline scaffolding by assistant), 2026.
"""
from __future__ import annotations

import csv
import os
import sys
import time
from typing import Any, Dict, Iterable, List

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUT_CSV = os.path.join(DATA_DIR, "gbif_occurrences.csv")

API = "https://api.gbif.org/v1/occurrence/search"

# Taxon keys verified via /v1/species/match on 2026-04-17.
TAXA: Dict[str, int] = {
    "Canis lupus":        5219173,
    "Capreolus capreolus": 5220126,
    "Alces alces":        2440940,
}
COUNTRIES = ("NO", "SE")
YEAR_RANGE = "1999,2024"

ACCEPT_BOR = {
    "HUMAN_OBSERVATION",
    "MACHINE_OBSERVATION",
    "LIVING_SPECIMEN",
    "OBSERVATION",
}

COLUMNS = [
    "gbifID", "species", "taxonKey",
    "decimalLatitude", "decimalLongitude",
    "year", "country", "datasetKey", "basisOfRecord",
    "coordinateUncertaintyInMeters",
]


def _get(params: Dict[str, Any], max_tries: int = 6) -> Dict[str, Any]:
    """GET with exponential backoff on 429/5xx/network errors."""
    wait = 2.0
    last_err: Any = None
    for i in range(max_tries):
        try:
            r = requests.get(API, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"HTTP {r.status_code}"
                time.sleep(wait)
                wait = min(wait * 2, 60)
                continue
            # Other non-200 -- surface it so we don't silently skip.
            r.raise_for_status()
        except requests.RequestException as e:
            last_err = e
            time.sleep(wait)
            wait = min(wait * 2, 60)
    raise RuntimeError(f"GBIF request failed after {max_tries} tries: {last_err}")


def fetch_species_country(species: str, taxon_key: int, country: str) -> Iterable[Dict[str, Any]]:
    offset = 0
    limit = 300
    total = None
    kept = 0
    dropped_bor = 0
    while True:
        params = {
            "taxonKey": taxon_key,
            "country": country,
            "hasCoordinate": "true",
            "year": YEAR_RANGE,
            "limit": limit,
            "offset": offset,
        }
        j = _get(params)
        if total is None:
            total = j.get("count", 0)
            print(f"  {species} / {country}: reported count = {total:,}")
        results = j.get("results", [])
        for rec in results:
            bor = rec.get("basisOfRecord")
            if bor not in ACCEPT_BOR:
                dropped_bor += 1
                continue
            lat = rec.get("decimalLatitude")
            lon = rec.get("decimalLongitude")
            yr = rec.get("year")
            if lat is None or lon is None or yr is None:
                continue
            yield {
                "gbifID": rec.get("gbifID"),
                "species": species,
                "taxonKey": taxon_key,
                "decimalLatitude": lat,
                "decimalLongitude": lon,
                "year": yr,
                "country": rec.get("country") or country,
                "datasetKey": rec.get("datasetKey"),
                "basisOfRecord": bor,
                "coordinateUncertaintyInMeters": rec.get("coordinateUncertaintyInMeters"),
            }
            kept += 1
        got = len(results)
        offset += got
        # Page-cap belt-and-braces:
        if j.get("endOfRecords") or got == 0:
            break
        # GBIF hard pagination cap ~100k; bail cleanly if we hit it.
        if offset >= 100_000:
            print(f"  WARNING: hit GBIF 100k offset cap for {species}/{country}, stopping early.")
            break
        if offset % 3000 == 0:
            print(f"    ... {species}/{country} offset={offset:,}, kept={kept:,}")
    print(f"  {species} / {country}: kept {kept:,} (dropped {dropped_bor:,} by basisOfRecord)")


def main() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    t0 = time.time()

    # Probe.
    try:
        probe = _get({"limit": 1})
        print(f"GBIF probe OK (global occ count ~ {probe.get('count', 'n/a')}).")
    except Exception as e:
        print(f"FATAL: cannot reach GBIF: {e}", file=sys.stderr)
        return 2

    rows: List[Dict[str, Any]] = []
    for species, key in TAXA.items():
        for country in COUNTRIES:
            print(f"Fetching {species} ({key}) in {country}...")
            for r in fetch_species_country(species, key, country):
                rows.append(r)

    print(f"Total rows kept across all species/countries: {len(rows):,}")
    tmp = OUT_CSV + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, OUT_CSV)
    print(f"Wrote {OUT_CSV} ({os.path.getsize(OUT_CSV)/1024:.0f} KB) in {time.time()-t0:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
