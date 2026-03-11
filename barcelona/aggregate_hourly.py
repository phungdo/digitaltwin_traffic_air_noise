#!/usr/bin/env python3
"""
Barcelona: Aggregate All Datasets to Hourly Resolution
=======================================================
Aligns noise (1-min), traffic (~15-min), and air quality (hourly wide)
to a common hourly time scale for modelling.

Aggregation methods:
  - Noise:  energy-averaged LAeq over 1 hour (logarithmic mean)
  - Traffic TRAMS:  mode of estatActual per hour per section
  - Traffic ITINERARIS:  mean of tempsActual per hour per itinerary
  - Air quality:  reshape from wide (H01-H24) to long format

Output (one CSV per domain):
  - noise_hourly.csv
  - traffic_trams_hourly.csv
  - traffic_itineraris_hourly.csv
  - air_quality_hourly.csv
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 1. Noise: 1-min LAeq → 1-hour LAeq (energy average)
# ---------------------------------------------------------------------------
def aggregate_noise():
    """
    LAeq must be aggregated using the energy (logarithmic) average:
      LAeq_1h = 10 * log10( mean( 10^(LAeq_1min / 10) ) )
    """
    print("=" * 65)
    print("1. NOISE: 1-min → hourly")
    print("=" * 65)

    filepath = SCRIPT_DIR / "noise_2025_09Set_XarxaSoroll_EqMonitor_Dades_1Min.csv"
    if not filepath.exists():
        print(f"  ✗ Not found: {filepath.name}")
        return None

    print(f"  Loading {filepath.name} (7.5M rows, chunked)...")

    chunks = []
    for i, chunk in enumerate(pd.read_csv(filepath, chunksize=500_000)):
        # Build datetime → extract hour
        chunk["datetime"] = pd.to_datetime(
            chunk["Any"].astype(str) + "-" +
            chunk["Mes"].astype(str).str.zfill(2) + "-" +
            chunk["Dia"].astype(str).str.zfill(2) + " " +
            chunk["Hora"],
            format="%Y-%m-%d %H:%M",
            errors="coerce"
        )
        chunk["hour"] = chunk["datetime"].dt.floor("h")

        # Convert to energy, aggregate, convert back
        chunk["energy"] = 10 ** (chunk["Nivell_LAeq_1min"] / 10)

        hourly = (
            chunk.groupby(["Id_Instal", "hour"])
            .agg(
                energy_mean=("energy", "mean"),
                n_samples=("energy", "count"),
            )
            .reset_index()
        )
        chunks.append(hourly)

        if (i + 1) % 5 == 0:
            print(f"    Processed {(i+1) * 500_000:,} rows...")

    result = pd.concat(chunks)

    # Re-aggregate (chunks may split same hour)
    result = (
        result.groupby(["Id_Instal", "hour"])
        .agg(
            energy_mean=("energy_mean", "mean"),
            n_samples=("n_samples", "sum"),
        )
        .reset_index()
    )

    result["LAeq_1h"] = 10 * np.log10(result["energy_mean"])
    result["LAeq_1h"] = result["LAeq_1h"].round(1)
    result = result.drop(columns=["energy_mean"])
    result = result.sort_values(["Id_Instal", "hour"])

    outpath = SCRIPT_DIR / "noise_hourly.csv"
    result.to_csv(outpath, index=False)
    print(f"  ✓ Saved {len(result):,} rows → {outpath.name}")
    print(f"    Sensors: {result['Id_Instal'].nunique()}")
    print(f"    Date range: {result['hour'].min()} to {result['hour'].max()}")
    print(f"    Samples per hour: median={result['n_samples'].median():.0f}, "
          f"min={result['n_samples'].min()}, max={result['n_samples'].max()}")
    return result


# ---------------------------------------------------------------------------
# 2. Traffic TRAMS: ~15-min → hourly (mode of state)
# ---------------------------------------------------------------------------
def aggregate_traffic_trams():
    print("\n" + "=" * 65)
    print("2. TRAFFIC TRAMS: ~15-min → hourly")
    print("=" * 65)

    filepath = SCRIPT_DIR / "traffic_2025_09_Setembre_TRAMS_TRAMS.csv"
    if not filepath.exists():
        print(f"  ✗ Not found: {filepath.name}")
        return None

    df = pd.read_csv(filepath)
    print(f"  ✓ Loaded {len(df):,} rows")

    # Parse timestamp: format YYYYMMDDHHmmss
    df["datetime"] = pd.to_datetime(df["data"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    df["hour"] = df["datetime"].dt.floor("h")

    # Aggregate: mode of estatActual per section per hour
    # Also compute distribution of states
    hourly = (
        df.groupby(["idTram", "hour"])
        .agg(
            estatActual_mode=("estatActual", lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else np.nan),
            estatActual_mean=("estatActual", "mean"),
            estatPrevist_mode=("estatPrevist", lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else np.nan),
            n_samples=("estatActual", "count"),
        )
        .reset_index()
    )
    hourly["estatActual_mean"] = hourly["estatActual_mean"].round(2)
    hourly = hourly.sort_values(["idTram", "hour"])

    outpath = SCRIPT_DIR / "traffic_trams_hourly.csv"
    hourly.to_csv(outpath, index=False)
    print(f"  ✓ Saved {len(hourly):,} rows → {outpath.name}")
    print(f"    Sections: {hourly['idTram'].nunique()}")
    print(f"    Date range: {hourly['hour'].min()} to {hourly['hour'].max()}")
    print(f"    Samples per hour: median={hourly['n_samples'].median():.0f}")
    return hourly


# ---------------------------------------------------------------------------
# 3. Traffic ITINERARIS: ~15-min → hourly (mean travel time)
# ---------------------------------------------------------------------------
def aggregate_traffic_itineraris():
    print("\n" + "=" * 65)
    print("3. TRAFFIC ITINERARIS: ~15-min → hourly")
    print("=" * 65)

    filepath = SCRIPT_DIR / "traffic_2025_09_Setembre_ITINERARIS_ITINERARIS.csv"
    if not filepath.exists():
        print(f"  ✗ Not found: {filepath.name}")
        return None

    df = pd.read_csv(filepath)
    print(f"  ✓ Loaded {len(df):,} rows")

    df["datetime"] = pd.to_datetime(df["data"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    df["hour"] = df["datetime"].dt.floor("h")

    # Filter to rows with actual data
    df_valid = df[df["infoDisponible"] == 1].copy()

    hourly = (
        df_valid.groupby(["idTram", "hour"])
        .agg(
            tempsActual_mean=("tempsActual", "mean"),
            tempsActual_max=("tempsActual", "max"),
            tempsPrevist_mean=("tempsPrevist", "mean"),
            n_samples=("tempsActual", "count"),
        )
        .reset_index()
    )
    hourly["tempsActual_mean"] = hourly["tempsActual_mean"].round(1)
    hourly["tempsPrevist_mean"] = hourly["tempsPrevist_mean"].round(1)
    hourly = hourly.sort_values(["idTram", "hour"])

    outpath = SCRIPT_DIR / "traffic_itineraris_hourly.csv"
    hourly.to_csv(outpath, index=False)
    print(f"  ✓ Saved {len(hourly):,} rows → {outpath.name}")
    print(f"    Itineraries: {hourly['idTram'].nunique()}")
    print(f"    Date range: {hourly['hour'].min()} to {hourly['hour'].max()}")
    return hourly


# ---------------------------------------------------------------------------
# 4. Air Quality: wide (H01-H24) → long hourly format
# ---------------------------------------------------------------------------
def reshape_air_quality():
    print("\n" + "=" * 65)
    print("4. AIR QUALITY: wide → long hourly")
    print("=" * 65)

    filepath = SCRIPT_DIR / "air_2025_09_Setembre_qualitat_aire_BCN.csv"
    contam_path = SCRIPT_DIR / "air_qualitat_aire_contaminants.csv"
    if not filepath.exists():
        print(f"  ✗ Not found: {filepath.name}")
        return None

    df = pd.read_csv(filepath)
    print(f"  ✓ Loaded {len(df):,} rows (wide format)")

    # Load contaminant names
    contam_map = {}
    if contam_path.exists():
        c = pd.read_csv(contam_path)
        contam_map = dict(zip(c["Codi_Contaminant"], c["Desc_Contaminant"]))

    # Melt H01-H24 and V01-V24
    id_cols = ["ESTACIO", "CODI_CONTAMINANT", "ANY", "MES", "DIA"]
    h_cols = [f"H{i:02d}" for i in range(1, 25)]
    v_cols = [f"V{i:02d}" for i in range(1, 25)]

    # Melt values
    h_melted = df[id_cols + h_cols].melt(
        id_vars=id_cols, var_name="hour_col", value_name="value"
    )
    h_melted["hour_num"] = h_melted["hour_col"].str.extract(r"(\d+)").astype(int)

    # Melt validation flags
    v_melted = df[id_cols + v_cols].melt(
        id_vars=id_cols, var_name="v_col", value_name="validation"
    )
    v_melted["hour_num"] = v_melted["v_col"].str.extract(r"(\d+)").astype(int)

    # Merge
    merged = h_melted.merge(v_melted, on=id_cols + ["hour_num"])

    # Build datetime
    merged["hour"] = pd.to_datetime(
        merged["ANY"].astype(str) + "-" +
        merged["MES"].astype(str).str.zfill(2) + "-" +
        merged["DIA"].astype(str).str.zfill(2) + " " +
        (merged["hour_num"] - 1).astype(str).str.zfill(2) + ":00",
        format="%Y-%m-%d %H:%M",
        errors="coerce"
    )

    # Clean up
    result = merged[["ESTACIO", "CODI_CONTAMINANT", "hour", "value", "validation"]].copy()
    result = result.rename(columns={
        "ESTACIO": "Estacio",
        "CODI_CONTAMINANT": "Codi_Contaminant"
    })

    # Add contaminant name
    result["contaminant"] = result["Codi_Contaminant"].map(contam_map)

    # Convert value to numeric
    result["value"] = pd.to_numeric(result["value"], errors="coerce")

    # Filter: keep only validated data
    result_valid = result[result["validation"] == "V"].copy()
    result_valid = result_valid.drop(columns=["validation"])
    result_valid = result_valid.sort_values(["Estacio", "Codi_Contaminant", "hour"])

    outpath = SCRIPT_DIR / "air_quality_hourly.csv"
    result_valid.to_csv(outpath, index=False)
    print(f"  ✓ Saved {len(result_valid):,} rows → {outpath.name}")
    print(f"    Stations: {result_valid['Estacio'].nunique()}")
    print(f"    Contaminants: {result_valid['Codi_Contaminant'].nunique()}")
    print(f"    Date range: {result_valid['hour'].min()} to {result_valid['hour'].max()}")

    # Show validation stats
    total = len(result)
    valid = len(result_valid)
    print(f"    Validation: {valid}/{total} ({100*valid/total:.1f}%) validated")

    return result_valid


# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
def print_summary():
    print("\n" + "=" * 65)
    print("SUMMARY — All datasets now at HOURLY resolution")
    print("=" * 65)
    print("""
    ┌─────────────────────┬───────────────┬────────────────────────┐
    │ Dataset             │ Original      │ Aggregated             │
    ├─────────────────────┼───────────────┼────────────────────────┤
    │ Noise               │ 1 minute      │ LAeq_1h (energy avg)   │
    │ Traffic TRAMS       │ ~15 minutes   │ mode + mean of state   │
    │ Traffic ITINERARIS  │ ~15 minutes   │ mean travel time (s)   │
    │ Air Quality         │ 1 hour (wide) │ 1 hour (long format)   │
    └─────────────────────┴───────────────┴────────────────────────┘

    All files share:  hour column (YYYY-MM-DD HH:00:00)
    Join key noise:   Id_Instal  ←→  matched_traffic_noise_pairs.csv
    Join key air:     Estacio    ←→  matched_traffic_airquality_pairs.csv
    Join key traffic: idTram
    """)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  Barcelona: Aggregate All Datasets to Hourly Resolution     ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    aggregate_noise()
    aggregate_traffic_trams()
    aggregate_traffic_itineraris()
    reshape_air_quality()
    print_summary()

    print("✓ Done!")


if __name__ == "__main__":
    main()
