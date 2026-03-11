#!/usr/bin/env python3
"""
Barcelona Spatial Matching: Traffic Sections ↔ Noise Sensors
=============================================================
Automatically finds and matches traffic road sections near noise sensors
using geopandas spatial join (sjoin_nearest).

Requirements:
    pip install pandas geopandas shapely matplotlib contextily

Input files (in same directory as this script):
    1. location_noise_XarxaSoroll_EquipsMonitor_Instal.csv  — noise sensor locations
    2. transit_relacio_trams.csv  — traffic section geometry
       (Download from: https://opendata-ajuntament.barcelona.cat/data/ca/dataset/transit-relacio-trams)

Output:
    - matched_traffic_noise_pairs.csv  — matched pairs with distances
    - matched_traffic_noise_map.png    — map visualization
    - Console summary statistics
"""

import os
import sys
import warnings
from pathlib import Path

import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString, MultiPoint
from shapely import wkt

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
MAX_DISTANCE_M = 200  # Maximum matching distance in metres
CRS_WGS84 = "EPSG:4326"
CRS_PROJECTED = "EPSG:25831"  # ETRS89 / UTM 31N — standard for Barcelona

# File paths
NOISE_LOCATION_FILE = SCRIPT_DIR / "location_noise_XarxaSoroll_EquipsMonitor_Instal.csv"
TRAFFIC_GEOM_FILE = SCRIPT_DIR / "transit_relacio_trams.csv"
TRAFFIC_GEOM_FILE_LONG = SCRIPT_DIR / "transit_relacio_trams_format_long.csv"
NOISE_DATA_FILE = SCRIPT_DIR / "noise_2025_09Set_XarxaSoroll_EqMonitor_Dades_1Min.csv"
TRAFFIC_DATA_FILE = SCRIPT_DIR / "traffic_2025_09_Setembre_TRAMS_TRAMS.csv"

OUTPUT_CSV = SCRIPT_DIR / "matched_traffic_noise_pairs.csv"
OUTPUT_MAP = SCRIPT_DIR / "matched_traffic_noise_map.png"


# ---------------------------------------------------------------------------
# 1. Load noise sensor locations
# ---------------------------------------------------------------------------
def load_noise_sensors() -> gpd.GeoDataFrame:
    """Load noise sensor locations and convert to GeoDataFrame."""
    print("=" * 65)
    print("STEP 1: Loading noise sensor locations")
    print("=" * 65)

    if not NOISE_LOCATION_FILE.exists():
        print(f"  ✗ File not found: {NOISE_LOCATION_FILE.name}")
        sys.exit(1)

    df = pd.read_csv(NOISE_LOCATION_FILE)
    print(f"  ✓ Loaded {len(df)} rows from {NOISE_LOCATION_FILE.name}")
    print(f"  Columns: {list(df.columns)}")

    # Filter to rows with valid coordinates
    df = df.dropna(subset=["Latitud", "Longitud"])
    df = df[(df["Latitud"] != 0) & (df["Longitud"] != 0)]
    print(f"  ✓ {len(df)} rows with valid coordinates")

    # Many sensors appear multiple times (installed/uninstalled at same location)
    # Keep the latest installation per sensor ID
    # First, parse dates
    if "Data_Instalacio" in df.columns:
        df["Data_Instalacio"] = pd.to_datetime(
            df["Data_Instalacio"], format="%d/%m/%Y", errors="coerce"
        )
        df = df.sort_values("Data_Instalacio", ascending=False)
        df = df.drop_duplicates(subset=["Id_Instal"], keep="first")
        print(f"  ✓ {len(df)} unique noise sensors after deduplication")

    # Also check which sensors appear in the September 2025 measurement data
    if NOISE_DATA_FILE.exists():
        print(f"  Checking overlap with measurement data...")
        # Read just the Id_Instal column from the large noise file
        noise_ids = set()
        chunk_reader = pd.read_csv(
            NOISE_DATA_FILE, usecols=["Id_Instal"], chunksize=500_000
        )
        for chunk in chunk_reader:
            noise_ids.update(chunk["Id_Instal"].unique())
        active_ids = noise_ids & set(df["Id_Instal"])
        print(f"  ✓ {len(noise_ids)} sensors in measurement data")
        print(f"  ✓ {len(active_ids)} of those have coordinates")

        # Flag active sensors
        df["has_measurements"] = df["Id_Instal"].isin(noise_ids)
    else:
        df["has_measurements"] = True

    # Create GeoDataFrame
    geometry = [Point(lon, lat) for lon, lat in zip(df["Longitud"], df["Latitud"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=CRS_WGS84)

    # Font category summary
    if "Font" in gdf.columns:
        print(f"\n  Sensor source breakdown:")
        for cat, count in gdf["Font"].value_counts().head(8).items():
            print(f"    {cat}: {count}")

    return gdf


# ---------------------------------------------------------------------------
# 2. Load traffic section geometry
# ---------------------------------------------------------------------------
def _parse_flat_coords(coord_str: str):
    """
    Parse a flat comma-separated coordinate string like:
      "2.112,41.384,2.101,41.381"
    into a LineString (if ≥2 points) or Point (if 1 point).
    Format: lon1,lat1,lon2,lat2,...
    """
    if pd.isna(coord_str):
        return None
    parts = [float(x.strip()) for x in str(coord_str).split(",") if x.strip()]
    if len(parts) < 2 or len(parts) % 2 != 0:
        return None
    coords = [(parts[i], parts[i + 1]) for i in range(0, len(parts), 2)]
    if len(coords) == 1:
        return Point(coords[0])
    return LineString(coords)


def _detect_geom_column(df: pd.DataFrame) -> tuple[str, str] | None:
    """
    Detect which column contains geometry and its format type.
    Returns (column_name, format_type) where format_type is 'wkt' or 'flat_coords'.
    """
    # First check for WKT-like content
    for col in df.columns:
        sample = df[col].dropna().iloc[:5].astype(str)
        if any(
            s.startswith(("LINESTRING", "MULTILINESTRING", "POINT", "POLYGON"))
            for s in sample
        ):
            return (col, "wkt")

    # Then check for named coordinate columns (flat comma-separated lon,lat pairs)
    coord_keywords = ["coordenades", "coordinates", "coords", "geometria"]
    for col in df.columns:
        if col.lower() in coord_keywords:
            # Verify it looks like flat coordinates (numbers separated by commas)
            sample = df[col].dropna().iloc[:3].astype(str)
            try:
                for s in sample:
                    parts = s.split(",")
                    if len(parts) >= 2:
                        float(parts[0].strip())
                        float(parts[1].strip())
                return (col, "flat_coords")
            except (ValueError, IndexError):
                continue

    # Check for generic geom columns
    geom_keywords = ["geom", "wkt", "the_geom", "shape"]
    for col in df.columns:
        if col.lower() in geom_keywords:
            return (col, "wkt")

    return None


def _parse_coordinate_columns(df: pd.DataFrame) -> gpd.GeoDataFrame | None:
    """Try to create geometry from lat/lon columns."""
    lat_cols = [c for c in df.columns if c.lower() in ("latitud", "lat", "latitude", "y", "coordy")]
    lon_cols = [c for c in df.columns if c.lower() in ("longitud", "lon", "longitude", "lng", "x", "coordx")]

    if lat_cols and lon_cols:
        lat_col, lon_col = lat_cols[0], lon_cols[0]
        df_valid = df.dropna(subset=[lat_col, lon_col])
        geometry = [Point(lon, lat) for lon, lat in zip(df_valid[lon_col], df_valid[lat_col])]
        return gpd.GeoDataFrame(df_valid, geometry=geometry, crs=CRS_WGS84)

    # Try ETRS89 coordinates
    x_cols = [c for c in df.columns if "etrs89" in c.lower() and "x" in c.lower()]
    y_cols = [c for c in df.columns if "etrs89" in c.lower() and "y" in c.lower()]
    if x_cols and y_cols:
        df_valid = df.dropna(subset=[x_cols[0], y_cols[0]])
        geometry = [Point(x, y) for x, y in zip(df_valid[x_cols[0]], df_valid[y_cols[0]])]
        return gpd.GeoDataFrame(df_valid, geometry=geometry, crs=CRS_PROJECTED)

    return None


def _build_lines_from_long_format(df: pd.DataFrame) -> gpd.GeoDataFrame | None:
    """
    If the file is in 'long format' with multiple coordinate rows per tram,
    group by idTram and build LineString geometries.
    """
    id_cols = [c for c in df.columns if c.lower() in ("idtram", "id_tram", "tram", "id")]
    if not id_cols:
        return None

    id_col = id_cols[0]
    gdf_points = _parse_coordinate_columns(df)
    if gdf_points is None:
        return None

    lines = []
    for tram_id, group in gdf_points.groupby(id_col):
        if len(group) >= 2:
            coords = list(group.geometry.apply(lambda p: (p.x, p.y)))
            lines.append({"idTram": tram_id, "geometry": LineString(coords)})
        elif len(group) == 1:
            lines.append({"idTram": tram_id, "geometry": group.geometry.iloc[0]})

    if lines:
        return gpd.GeoDataFrame(lines, crs=gdf_points.crs)
    return None


def load_traffic_sections() -> gpd.GeoDataFrame:
    """Load traffic section geometry with adaptive format detection."""
    print("\n" + "=" * 65)
    print("STEP 2: Loading traffic section geometry")
    print("=" * 65)

    # Try multiple potential files
    for filepath in [TRAFFIC_GEOM_FILE, TRAFFIC_GEOM_FILE_LONG]:
        if filepath.exists():
            print(f"  ✓ Found: {filepath.name}")
            break
    else:
        # Look for any file that might contain the geometry
        candidates = list(SCRIPT_DIR.glob("*relacio*trams*")) + \
                     list(SCRIPT_DIR.glob("*transit*relacio*"))
        if candidates:
            filepath = candidates[0]
            print(f"  ✓ Found candidate: {filepath.name}")
        else:
            print("  ✗ Traffic section geometry file not found!")
            print("    Please download 'transit_relacio_trams.csv' from:")
            print("    https://opendata-ajuntament.barcelona.cat/data/ca/dataset/transit-relacio-trams")
            print(f"    and place it in: {SCRIPT_DIR}")
            sys.exit(1)

    # Read the CSV
    try:
        df = pd.read_csv(filepath, low_memory=False)
    except Exception:
        df = pd.read_csv(filepath, sep=";", low_memory=False)

    print(f"  ✓ Loaded {len(df)} rows, {len(df.columns)} columns")
    print(f"  Columns: {list(df.columns)}")

    # Show first row for debugging
    print(f"  First row sample:")
    for col in df.columns[:10]:
        print(f"    {col}: {df[col].iloc[0]}")

    # Strategy 1: Detect geometry column
    geom_info = _detect_geom_column(df)
    if geom_info:
        geom_col, fmt = geom_info

        if fmt == "flat_coords":
            # Parse flat comma-separated lon,lat pairs into LineString/Point
            print(f"\n  → Detected flat coordinate pairs in column: '{geom_col}'")
            df["geometry"] = df[geom_col].apply(_parse_flat_coords)
            df = df[df["geometry"].notna()]
            gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=CRS_WGS84)
        else:
            # WKT format
            print(f"\n  → Detected WKT geometry in column: '{geom_col}'")
            df["geometry"] = df[geom_col].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=CRS_WGS84)

        # Identify the tram ID column
        id_cols = [c for c in df.columns if c.lower() in ("idtram", "id_tram", "tram", "id", "codi")]
        if id_cols:
            gdf = gdf.rename(columns={id_cols[0]: "idTram"})
        print(f"  ✓ Created {len(gdf)} geometry features")
        geom_types = gdf.geometry.geom_type.value_counts()
        for gt, cnt in geom_types.items():
            print(f"    {gt}: {cnt}")
        return gdf

    # Strategy 2: Look for lat/lon or ETRS89 coordinate columns
    gdf = _parse_coordinate_columns(df)
    if gdf is not None:
        print(f"\n  → Detected point coordinates")
        # Check if this is a long format (multiple points per tram)
        id_cols = [c for c in df.columns if c.lower() in ("idtram", "id_tram", "tram", "id", "codi")]
        if id_cols:
            id_col = id_cols[0]
            n_unique = df[id_col].nunique()
            if n_unique < len(df) * 0.5:  # Many rows per ID = long format
                print(f"  → Detected long format ({n_unique} unique IDs in {len(df)} rows)")
                gdf_lines = _build_lines_from_long_format(df)
                if gdf_lines is not None:
                    print(f"  ✓ Built {len(gdf_lines)} line geometries from points")
                    return gdf_lines
            gdf = gdf.rename(columns={id_col: "idTram"})

        gdf = gdf.drop_duplicates(subset=["idTram"] if "idTram" in gdf.columns else None)
        print(f"  ✓ Created {len(gdf)} point features")
        return gdf

    # Strategy 3: Look for 'Descripció' with start/end street addresses
    # (Generate centroids using Nominatim geocoding — requires internet)
    desc_cols = [c for c in df.columns if "descri" in c.lower() or "nom" in c.lower()]
    if desc_cols:
        print(f"\n  ⚠ Found description columns but no coordinates: {desc_cols}")
        print("    File has street descriptions but no geometry.")
        print("    Try downloading 'transit_relacio_trams_format_long.csv' instead,")
        print("    which may include coordinates.")

    print("\n  ✗ Could not detect any geometry in the file.")
    print(f"    Columns found: {list(df.columns)}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 3. Spatial matching
# ---------------------------------------------------------------------------
def match_nearest(
    noise_gdf: gpd.GeoDataFrame,
    traffic_gdf: gpd.GeoDataFrame,
    max_distance_m: float = MAX_DISTANCE_M,
) -> gpd.GeoDataFrame:
    """Find nearest traffic section for each noise sensor within max_distance."""
    print("\n" + "=" * 65)
    print("STEP 3: Spatial matching (sjoin_nearest)")
    print("=" * 65)

    # Reproject both to UTM for accurate metre-based distances
    noise_proj = noise_gdf.to_crs(CRS_PROJECTED)
    traffic_proj = traffic_gdf.to_crs(CRS_PROJECTED)
    print(f"  ✓ Reprojected to {CRS_PROJECTED} (UTM 31N)")
    print(f"  Noise sensors: {len(noise_proj)} | Traffic sections: {len(traffic_proj)}")

    # Perform nearest join
    matched = gpd.sjoin_nearest(
        noise_proj,
        traffic_proj,
        how="left",
        max_distance=max_distance_m,
        distance_col="distance_m",
    )

    # Summarize
    n_matched = matched["distance_m"].notna().sum()
    n_unmatched = matched["distance_m"].isna().sum()
    print(f"\n  Results (max distance = {max_distance_m}m):")
    print(f"    ✓ Matched:   {n_matched} sensor-section pairs")
    print(f"    ✗ Unmatched: {n_unmatched} sensors (no traffic section within {max_distance_m}m)")

    if n_matched > 0:
        dist = matched.loc[matched["distance_m"].notna(), "distance_m"]
        print(f"\n  Distance statistics:")
        print(f"    Min:    {dist.min():.1f} m")
        print(f"    Median: {dist.median():.1f} m")
        print(f"    Mean:   {dist.mean():.1f} m")
        print(f"    Max:    {dist.max():.1f} m")

    return matched


# ---------------------------------------------------------------------------
# 4. Output results
# ---------------------------------------------------------------------------
def save_results(matched: gpd.GeoDataFrame, noise_gdf: gpd.GeoDataFrame,
                 traffic_gdf: gpd.GeoDataFrame):
    """Save matched pairs to CSV and generate map."""
    print("\n" + "=" * 65)
    print("STEP 4: Saving results")
    print("=" * 65)

    # Prepare output columns
    out_cols = ["Id_Instal", "distance_m"]

    # Add noise sensor info if available
    for col in ["Nom_Carrer", "Num_Carrer", "Nom_Barri", "Nom_Districte", "Font",
                 "has_measurements", "Latitud", "Longitud"]:
        if col in matched.columns:
            out_cols.append(col)

    # Add traffic section info if available
    if "idTram" in matched.columns:
        out_cols.append("idTram")
    for col in matched.columns:
        if col.startswith("Desc") or col.startswith("nom") or col.startswith("Nom"):
            if col not in out_cols:
                out_cols.append(col)

    # Filter to matched pairs only
    result = matched.loc[matched["distance_m"].notna(), 
                         [c for c in out_cols if c in matched.columns]].copy()
    result["distance_m"] = result["distance_m"].round(1)
    result = result.sort_values("distance_m")

    # Save CSV
    result.to_csv(OUTPUT_CSV, index=False)
    print(f"  ✓ Saved {len(result)} matched pairs to: {OUTPUT_CSV.name}")

    # Generate map
    try:
        _generate_map(noise_gdf, traffic_gdf, matched)
    except Exception as e:
        print(f"  ⚠ Map generation failed: {e}")
        print("    (Install contextily for basemap: pip install contextily)")


def _generate_map(noise_gdf, traffic_gdf, matched):
    """Generate a map showing sensors, traffic sections, and matches."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(14, 12))

    # Plot traffic sections
    traffic_plot = traffic_gdf.to_crs(CRS_WGS84)
    geom_types = set(traffic_plot.geometry.geom_type)
    if "LineString" in geom_types or "MultiLineString" in geom_types:
        traffic_plot.plot(ax=ax, color="#3388ff", linewidth=1.5, alpha=0.6,
                          label="Traffic sections")
    else:
        traffic_plot.plot(ax=ax, color="#3388ff", markersize=15, alpha=0.6,
                          marker="s", label="Traffic sections")

    # Plot noise sensors
    noise_plot = noise_gdf.to_crs(CRS_WGS84)
    noise_matched = noise_plot[noise_plot["Id_Instal"].isin(
        matched.loc[matched["distance_m"].notna(), "Id_Instal"])]
    noise_unmatched = noise_plot[~noise_plot["Id_Instal"].isin(
        matched.loc[matched["distance_m"].notna(), "Id_Instal"])]

    if len(noise_unmatched) > 0:
        noise_unmatched.plot(ax=ax, color="#999999", markersize=10, alpha=0.4,
                              marker="o", label=f"Unmatched sensors ({len(noise_unmatched)})")
    if len(noise_matched) > 0:
        noise_matched.plot(ax=ax, color="#ff4444", markersize=25, alpha=0.8,
                            marker="o", label=f"Matched sensors ({len(noise_matched)})",
                            edgecolor="white", linewidth=0.5)

    # Try to add basemap
    try:
        import contextily as ctx
        ctx.add_basemap(ax, crs=CRS_WGS84, source=ctx.providers.CartoDB.Positron,
                        alpha=0.8)
    except ImportError:
        pass
    except Exception:
        pass

    ax.set_title(
        f"Barcelona: Traffic Sections ↔ Noise Sensors\n"
        f"({len(noise_matched)} matches within {MAX_DISTANCE_M}m)",
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
# 5. Summary report
# ---------------------------------------------------------------------------
def print_summary(matched: gpd.GeoDataFrame):
    """Print final summary."""
    print("\n" + "=" * 65)
    print("SUMMARY")
    print("=" * 65)

    valid = matched[matched["distance_m"].notna()]
    if len(valid) == 0:
        print("  No matches found! Try increasing MAX_DISTANCE_M.")
        return

    # By district
    if "Nom_Districte" in valid.columns:
        print("\n  Matches by district:")
        for district, count in valid["Nom_Districte"].value_counts().items():
            print(f"    {district}: {count}")

    # By noise source type
    if "Font" in valid.columns:
        print("\n  Matches by noise source type:")
        for font, count in valid["Font"].value_counts().items():
            print(f"    {font}: {count}")

    # Active sensors with measurements
    if "has_measurements" in valid.columns:
        n_active = valid["has_measurements"].sum()
        print(f"\n  Matched sensors with Sep 2025 measurements: {n_active}/{len(valid)}")

    # Unique traffic sections matched
    if "idTram" in valid.columns:
        n_trams = valid["idTram"].nunique()
        print(f"  Unique traffic sections matched: {n_trams}")

    print(f"\n  Output files:")
    print(f"    {OUTPUT_CSV.name}")
    print(f"    {OUTPUT_MAP.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  Barcelona: Traffic Sections ↔ Noise Sensors Matcher        ║")
    print("║  Using geopandas sjoin_nearest                              ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    noise_gdf = load_noise_sensors()
    traffic_gdf = load_traffic_sections()
    matched = match_nearest(noise_gdf, traffic_gdf, MAX_DISTANCE_M)
    save_results(matched, noise_gdf, traffic_gdf)
    print_summary(matched)

    print("\n✓ Done!")


if __name__ == "__main__":
    main()
