#!/usr/bin/env python3
"""
Barcelona Spatial Matching: Traffic Sections ↔ Air Quality Stations
====================================================================
Automatically finds and matches traffic road sections near air quality
monitoring stations using geopandas spatial join (sjoin_nearest).

Requirements:
    pip install pandas geopandas shapely matplotlib contextily

Input files (in same directory as this script):
    1. air_location_2025_qualitat_aire_estacions.csv  — station locations
    2. transit_relacio_trams.csv  — traffic section geometry

Output:
    - matched_traffic_airquality_pairs.csv  — matched pairs with distances
    - matched_traffic_airquality_map.png    — map visualization
    - Console summary statistics
"""

import sys
import warnings
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
MAX_DISTANCE_M = 500  # Air quality stations are sparser → larger threshold
CRS_WGS84 = "EPSG:4326"
CRS_PROJECTED = "EPSG:25831"  # ETRS89 / UTM 31N — standard for Barcelona

# File paths
AIR_LOCATION_FILE = SCRIPT_DIR / "air_location_2025_qualitat_aire_estacions.csv"
AIR_CONTAMINANTS_FILE = SCRIPT_DIR / "air_qualitat_aire_contaminants.csv"
TRAFFIC_GEOM_FILE = SCRIPT_DIR / "transit_relacio_trams.csv"
TRAFFIC_GEOM_FILE_LONG = SCRIPT_DIR / "transit_relacio_trams_format_long.csv"

OUTPUT_CSV = SCRIPT_DIR / "matched_traffic_airquality_pairs.csv"
OUTPUT_MAP = SCRIPT_DIR / "matched_traffic_airquality_map.png"


# ---------------------------------------------------------------------------
# 1. Load air quality station locations
# ---------------------------------------------------------------------------
def load_air_stations() -> gpd.GeoDataFrame:
    """Load air quality station locations and convert to GeoDataFrame."""
    print("=" * 65)
    print("STEP 1: Loading air quality station locations")
    print("=" * 65)

    if not AIR_LOCATION_FILE.exists():
        print(f"  ✗ File not found: {AIR_LOCATION_FILE.name}")
        sys.exit(1)

    df = pd.read_csv(AIR_LOCATION_FILE)
    print(f"  ✓ Loaded {len(df)} rows from {AIR_LOCATION_FILE.name}")
    print(f"  Columns: {list(df.columns)}")

    # Each station appears multiple times (once per contaminant it measures)
    # Get unique stations
    station_cols = ["Estacio", "nom_cabina", "Longitud", "Latitud", "ubicacio",
                    "Nom_districte", "Nom_barri", "Clas_1", "Clas_2"]
    available_cols = [c for c in station_cols if c in df.columns]
    stations = df[available_cols].drop_duplicates(subset=["Estacio"])
    print(f"  ✓ {len(stations)} unique stations")

    # Get contaminants measured per station
    if AIR_CONTAMINANTS_FILE.exists():
        contam_df = pd.read_csv(AIR_CONTAMINANTS_FILE)
        contam_map = dict(zip(contam_df["Codi_Contaminant"], contam_df["Desc_Contaminant"]))
        contam_per_station = (
            df.groupby("Estacio")["Codi_Contaminant"]
            .apply(lambda x: ", ".join(
                contam_map.get(c, str(c)) for c in sorted(x.unique()) if c < 100
            ))
            .reset_index()
            .rename(columns={"Codi_Contaminant": "Contaminants"})
        )
        stations = stations.merge(contam_per_station, on="Estacio", how="left")

    # Filter to rows with valid coordinates
    stations = stations.dropna(subset=["Latitud", "Longitud"])
    print(f"  ✓ {len(stations)} stations with valid coordinates")

    # Create GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in
                zip(stations["Longitud"], stations["Latitud"])]
    gdf = gpd.GeoDataFrame(stations, geometry=geometry, crs=CRS_WGS84)

    # Print station details
    print(f"\n  Station details:")
    for _, row in gdf.iterrows():
        cls = row.get("Clas_2", "?")
        contam = row.get("Contaminants", "?")
        print(f"    [{row['Estacio']}] {row['nom_cabina']} ({cls}) — {contam}")

    return gdf


# ---------------------------------------------------------------------------
# 2. Load traffic section geometry (reuse from match_traffic_noise.py)
# ---------------------------------------------------------------------------
def _parse_flat_coords(coord_str: str):
    """Parse flat comma-separated lon,lat pairs into LineString/Point."""
    if pd.isna(coord_str):
        return None
    parts = [float(x.strip()) for x in str(coord_str).split(",") if x.strip()]
    if len(parts) < 2 or len(parts) % 2 != 0:
        return None
    coords = [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]
    if len(coords) == 1:
        return Point(coords[0])
    return LineString(coords)


def load_traffic_sections() -> gpd.GeoDataFrame:
    """Load traffic section geometry."""
    print("\n" + "=" * 65)
    print("STEP 2: Loading traffic section geometry")
    print("=" * 65)

    for filepath in [TRAFFIC_GEOM_FILE, TRAFFIC_GEOM_FILE_LONG]:
        if filepath.exists():
            print(f"  ✓ Found: {filepath.name}")
            break
    else:
        candidates = list(SCRIPT_DIR.glob("*relacio*trams*")) + \
                     list(SCRIPT_DIR.glob("*transit*relacio*"))
        if candidates:
            filepath = candidates[0]
            print(f"  ✓ Found candidate: {filepath.name}")
        else:
            print("  ✗ Traffic section geometry file not found!")
            sys.exit(1)

    try:
        df = pd.read_csv(filepath, low_memory=False)
    except Exception:
        df = pd.read_csv(filepath, sep=";", low_memory=False)

    print(f"  ✓ Loaded {len(df)} rows, {len(df.columns)} columns")
    print(f"  Columns: {list(df.columns)}")

    # Parse geometry from Coordenades column (flat lon,lat pairs)
    coord_col = None
    for col in df.columns:
        if col.lower() in ("coordenades", "coordinates", "coords", "geometria"):
            coord_col = col
            break

    if coord_col:
        print(f"  → Parsing coordinates from '{coord_col}'")
        df["geometry"] = df[coord_col].apply(_parse_flat_coords)
        df = df[df["geometry"].notna()]
        gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=CRS_WGS84)
    else:
        # Try WKT
        from shapely import wkt
        for col in df.columns:
            sample = df[col].dropna().iloc[:5].astype(str)
            if any(s.startswith(("LINESTRING", "POINT")) for s in sample):
                df["geometry"] = df[col].apply(wkt.loads)
                gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=CRS_WGS84)
                break
        else:
            print("  ✗ Could not detect geometry")
            sys.exit(1)

    # Rename ID column
    id_cols = [c for c in df.columns if c.lower() in ("idtram", "id_tram", "tram")]
    if id_cols:
        gdf = gdf.rename(columns={id_cols[0]: "idTram"})

    print(f"  ✓ Created {len(gdf)} geometry features")
    return gdf


# ---------------------------------------------------------------------------
# 3. Spatial matching — find ALL traffic sections near each station
# ---------------------------------------------------------------------------
def match_nearest(
    air_gdf: gpd.GeoDataFrame,
    traffic_gdf: gpd.GeoDataFrame,
    max_distance_m: float = MAX_DISTANCE_M,
) -> gpd.GeoDataFrame:
    """Find all traffic sections within max_distance of each air station."""
    print("\n" + "=" * 65)
    print("STEP 3: Spatial matching (sjoin_nearest)")
    print("=" * 65)

    air_proj = air_gdf.to_crs(CRS_PROJECTED)
    traffic_proj = traffic_gdf.to_crs(CRS_PROJECTED)
    print(f"  ✓ Reprojected to {CRS_PROJECTED} (UTM 31N)")
    print(f"  Air stations: {len(air_proj)} | Traffic sections: {len(traffic_proj)}")

    # Buffer each station and find all traffic sections within distance
    air_buffered = air_proj.copy()
    air_buffered["geometry"] = air_proj.geometry.buffer(max_distance_m)

    # Spatial join: find all traffic sections intersecting the buffer
    joined = gpd.sjoin(traffic_proj, air_buffered, how="inner", predicate="intersects")

    if len(joined) == 0:
        print(f"  ✗ No traffic sections found within {max_distance_m}m of any station")
        # Fallback to nearest join
        print("  Falling back to nearest-match approach...")
        joined = gpd.sjoin_nearest(
            air_proj, traffic_proj, how="left",
            max_distance=max_distance_m * 2,
            distance_col="distance_m",
        )
        return joined

    # Calculate actual distances from station point to traffic line
    results = []
    for _, row in joined.iterrows():
        tram_geom = row.geometry  # traffic section geometry
        station_id = row["Estacio"]
        station_point = air_proj.loc[air_proj["Estacio"] == station_id].geometry.iloc[0]
        dist = tram_geom.distance(station_point)
        results.append({**row.to_dict(), "distance_m": round(dist, 1)})

    result_df = pd.DataFrame(results)
    # Filter to actual max distance (buffer is approximate for lines)
    result_df = result_df[result_df["distance_m"] <= max_distance_m]
    result_df = result_df.sort_values(["Estacio", "distance_m"])

    # Summary
    n_stations_matched = result_df["Estacio"].nunique()
    n_trams_matched = result_df["idTram"].nunique()
    print(f"\n  Results (max distance = {max_distance_m}m):")
    print(f"    Stations with nearby traffic: {n_stations_matched}/{len(air_gdf)}")
    print(f"    Total matches: {len(result_df)}")
    print(f"    Unique traffic sections: {n_trams_matched}")

    if len(result_df) > 0:
        print(f"\n  Distance statistics:")
        print(f"    Min:    {result_df['distance_m'].min():.1f} m")
        print(f"    Median: {result_df['distance_m'].median():.1f} m")
        print(f"    Mean:   {result_df['distance_m'].mean():.1f} m")
        print(f"    Max:    {result_df['distance_m'].max():.1f} m")

    # Per-station breakdown
    print(f"\n  Matches per station:")
    for station_id in sorted(result_df["Estacio"].unique()):
        subset = result_df[result_df["Estacio"] == station_id]
        name = subset["nom_cabina"].iloc[0] if "nom_cabina" in subset else "?"
        cls = subset["Clas_2"].iloc[0] if "Clas_2" in subset else "?"
        print(f"    [{station_id}] {name} ({cls}): "
              f"{len(subset)} sections, nearest {subset['distance_m'].min():.0f}m")

    return result_df


# ---------------------------------------------------------------------------
# 4. Output results
# ---------------------------------------------------------------------------
def save_results(result_df: pd.DataFrame, air_gdf: gpd.GeoDataFrame,
                 traffic_gdf: gpd.GeoDataFrame):
    """Save matched pairs to CSV and generate map."""
    print("\n" + "=" * 65)
    print("STEP 4: Saving results")
    print("=" * 65)

    out_cols = ["Estacio", "nom_cabina", "Clas_2", "idTram", "distance_m"]
    # Add description if available
    if "Descripció" in result_df.columns:
        out_cols.append("Descripció")
    for col in ["Nom_districte", "Nom_barri", "Contaminants"]:
        if col in result_df.columns:
            out_cols.append(col)

    output = result_df[[c for c in out_cols if c in result_df.columns]].copy()
    output.to_csv(OUTPUT_CSV, index=False)
    print(f"  ✓ Saved {len(output)} matched pairs to: {OUTPUT_CSV.name}")

    # Generate map
    try:
        _generate_map(air_gdf, traffic_gdf, result_df)
    except Exception as e:
        print(f"  ⚠ Map generation failed: {e}")


def _generate_map(air_gdf, traffic_gdf, result_df):
    """Generate a map showing stations, traffic sections, and matches."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(14, 12))

    # Plot all traffic sections (light)
    traffic_plot = traffic_gdf.to_crs(CRS_WGS84)
    traffic_plot.plot(ax=ax, color="#aaccff", linewidth=1, alpha=0.4,
                      label="All traffic sections")

    # Highlight matched traffic sections
    if "idTram" in result_df.columns:
        matched_ids = set(result_df["idTram"].unique())
        matched_traffic = traffic_plot[traffic_plot["idTram"].isin(matched_ids)]
        matched_traffic.plot(ax=ax, color="#3388ff", linewidth=2.5, alpha=0.8,
                              label=f"Matched sections ({len(matched_ids)})")

    # Plot air stations with labels
    air_plot = air_gdf.to_crs(CRS_WGS84)
    air_plot.plot(ax=ax, color="#ff4444", markersize=120, alpha=0.9,
                  marker="^", edgecolor="white", linewidth=1.5, zorder=5,
                  label=f"Air quality stations ({len(air_plot)})")

    # Add station labels
    for _, row in air_plot.iterrows():
        name = row["nom_cabina"].replace("Barcelona - ", "")
        ax.annotate(name, xy=(row.geometry.x, row.geometry.y),
                    xytext=(8, 8), textcoords="offset points",
                    fontsize=8, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              alpha=0.8, edgecolor="#ff4444"))

    # Draw buffer circles (approximate — in WGS84 degrees)
    buffer_deg = MAX_DISTANCE_M / 111_000  # rough deg conversion
    for _, row in air_plot.iterrows():
        circle = row.geometry.buffer(buffer_deg)
        gpd.GeoSeries([circle], crs=CRS_WGS84).plot(
            ax=ax, facecolor="none", edgecolor="#ff4444",
            linewidth=1, linestyle="--", alpha=0.5)

    # Basemap
    try:
        import contextily as ctx
        ctx.add_basemap(ax, crs=CRS_WGS84, source=ctx.providers.CartoDB.Positron,
                        alpha=0.8)
    except Exception:
        pass

    ax.set_title(
        f"Barcelona: Traffic Sections ↔ Air Quality Stations\n"
        f"({len(result_df)} matches within {MAX_DISTANCE_M}m)",
        fontsize=14, fontweight="bold"
    )
    ax.legend(loc="upper left", fontsize=10)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    plt.tight_layout()
    plt.savefig(OUTPUT_MAP, dpi=150, bbox_inches="tight")
    print(f"  ✓ Saved map to: {OUTPUT_MAP.name}")
    plt.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  Barcelona: Traffic Sections ↔ Air Quality Stations Matcher ║")
    print("║  Using geopandas spatial join                               ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    air_gdf = load_air_stations()
    traffic_gdf = load_traffic_sections()
    result_df = match_nearest(air_gdf, traffic_gdf, MAX_DISTANCE_M)
    save_results(result_df, air_gdf, traffic_gdf)

    print("\n✓ Done!")


if __name__ == "__main__":
    main()
