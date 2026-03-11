# Data Dictionary — Madrid Traffic x Air Pollution

**Last updated:** 2026-02-25 (v2 — verified against real data files and official documentation)

**Sources verified:**
- Traffic CSV: `300233-85-aforo-trafico-permanentes-csv` (April 2018 sample)
- Air quality CSV: `may_mo18.csv` (May 2018 hourly, 4,650 rows)
- Official PDF: "Calidad del aire — Intérprete de ficheros de datos horarios, diarios y tiempo real" (datos abiertos Madrid)

---

## 1. Traffic Counts (T1) — Raw Schema

**Source file format:** Semicolon-delimited CSV, one file per month.
**Encoding:** UTF-8 (some older files may be ISO-8859-1).
**Delimiter:** Semicolon (`;`).
**Header:** `FDIA;FEST;FSEN;HOR1;HOR2;HOR3;HOR4;HOR5;HOR6;HOR7;HOR8;HOR9;HOR10;HOR11;HOR12`
**Row count per month:** ~3,600–7,400 depending on number of stations active and whether streets are bidirectional.
**Download URL pattern:** `https://datos.madrid.es/dataset/300233-0-aforo-trafico-permanentes/resource/300233-{ID}-aforo-trafico-permanentes-csv` (resource IDs are non-sequential; extract from catalog page).

| Field | Type | Description | Example | Notes |
|-------|------|-------------|---------|-------|
| FDIA | string | Date of measurement, DD/MM/YY format | `01/04/18` | Two-digit year. Parse with explicit century handling. |
| FEST | string | Station identifier | `ES01` | ES01 through ES60. Not all active at all times. |
| FSEN | string | Direction + time block code | `1-` | See FSEN encoding table below. May be blank for one-way streets. |
| HOR1–HOR12 | integer | Vehicle count for each hour in the half-day block | `743` | May contain blanks or zeros for missing data. |

### FSEN encoding (verified from official documentation)

| Code | Direction | Time Block | Hour Mapping |
|------|-----------|------------|--------------|
| `1-` | Sense 1 | Morning | HOR1=01:00, HOR2=02:00, ..., HOR12=12:00 |
| `1=` | Sense 1 | Afternoon/Night | HOR1=13:00, HOR2=14:00, ..., HOR12=24:00 |
| `2-` | Sense 2 | Morning | HOR1=01:00, HOR2=02:00, ..., HOR12=12:00 |
| `2=` | Sense 2 | Afternoon/Night | HOR1=13:00, HOR2=14:00, ..., HOR12=24:00 |
| *(blank)* | Single direction | Morning | HOR1=01:00, ..., HOR12=12:00 |
| *(blank with `=`)* | Single direction | Afternoon/Night | HOR1=13:00, ..., HOR12=24:00 |

**Row structure:** One record = one station × one direction × one half-day (12 hours). A complete bidirectional station-day produces **4 rows**. A one-way street produces **2 rows**.

**Worked example** (from real data, ES01 on 01/04/2018 — Easter Sunday):
```
01/04/18;ES01;1-;743;615;397;289;282;313;180;195;144;275;420;502
→ Direction 1, 01:00–12:00: 743 vehicles at 1AM, 615 at 2AM, ..., 502 at noon

01/04/18;ES01;1=;647;672;501;934;1110;1148;1122;1150;1152;948;848;578
→ Direction 1, 13:00–24:00: 647 at 1PM, 672 at 2PM, ..., 578 at midnight

01/04/18;ES01;2-;456;367;304;247;254;292;169;176;297;460;810;869
→ Direction 2, 01:00–12:00

01/04/18;ES01;2=;882;846;730;797;956;939;814;822;739;583;512;347
→ Direction 2, 13:00–24:00
```

**Total daily vehicles at ES01:** Sum all 48 values ≈ 24,000 (both directions). Easter Sunday → lower than typical weekday.

### Data quality notes — Traffic

- **Data gap:** Late 2021 to mid-2022 due to system migration (confirmed by portal notice).
- **Sensor type:** Inductive loop detectors (not cameras). Station ES47 (Méndez Álvaro) had incorrect coordinates in early files; corrected to 40.397062, -3.681941.
- **Zero values:** Can mean truly zero traffic OR sensor offline. Distinguish by checking neighboring hours: an isolated zero surrounded by normal values → likely sensor failure.
- **Outlier threshold:** >50,000 vehicles/hour at any station is physically impossible → sensor error.

---

## 2. Traffic Station Locations (T2/T3)

**Source:** Excel tab "UBICACIÓN ESTACIONES" in monthly XLS files, or companion geo file "Ubicación de estaciones permanentes y sentidos de calles."

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| Station ID | string | Matches FEST in traffic data | `ES01` |
| Name | string | Street or location name | `Calle Méndez Álvaro` |
| Latitude | float | WGS84, decimal degrees | `40.397062` |
| Longitude | float | WGS84, decimal degrees | `-3.681941` |
| Sense 1 orientation | string | Direction description | `Norte-Sur` |
| Sense 2 orientation | string | Direction description | `Sur-Norte` |

---

## 3. Air Quality Hourly (A1) — Raw Schema

**Source file format:** Semicolon-delimited CSV, one file per year (historical) or rolling 20-minute update (real-time).
**Delimiter:** Semicolon (`;`).
**Structure:** Wide format. Each row = one station × one pollutant × one day. Columns H01–H24 give hourly values; V01–V24 give corresponding validation flags.
**Download:** Yearly CSVs from datos.madrid.es catalog. Real-time rolling CSV updates every 20 minutes.

### 3.1 Column layout (verified from `may_mo18.csv`)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| PROVINCIA | integer | Province code (always 28 for Madrid) | `28` |
| MUNICIPIO | integer | Municipality code (always 079 for Madrid city) | `79` |
| ESTACION | integer | Station number (see Annex I) | `4` |
| MAGNITUD | integer | Pollutant code (see Annex II) | `8` (= NO2) |
| PUNTO_MUESTREO | string | Composite sampling point ID | `28079004_8_8` |
| ANO | integer | Year (4 digits from Oct 2017 onward; 2 digits before) | `2018` |
| MES | integer | Month | `5` |
| DIA | integer | Day of month | `1` |
| H01–H24 | float | Hourly measured value | `24.0` |
| V01–V24 | string | Validation flag for each hour | `V` |

### 3.2 PUNTO_MUESTREO decoding

Format: `{PROVINCIA}{MUNICIPIO}{ESTACION}_{MAGNITUD}_{TECNICA}`

Example: `28079004_8_8` = Province 28, Municipality 079, Station 004, MAGNITUD 8 (NO2), Technique 08 (Chemiluminescence)

This is a **composite key** that encodes station + pollutant + measurement technique in one field. It serves as a redundant cross-check against the separate ESTACION and MAGNITUD columns.

### 3.3 Hour convention (from official PDF, Section 7 — Notes)

- **H01** = value at 01:00 local time (Madrid), **H24** = value at midnight (23:00–24:00).
- **H24 calculation:** Mean of 6 ten-minute values from 23:00 to 24:00, local time.
- **Timezone:** All timestamps are in **Madrid local time** (UTC+1 in winter / UTC+2 in summer).
- **DST spring forward:** Day has 23 hours → daily aggregation uses 23 values.
- **DST fall back:** Day has 25 hours → the duplicate hour's data is **discarded** (not averaged).
- **General hourly calculation:** Each hourly value = arithmetic mean of 6 ten-minute instrument readings.

### 3.4 Data format variants (pre- vs post-October 2017)

| Period | Year format | Example raw line |
|--------|-------------|------------------|
| Before Oct 2017 | 2-digit year | `28,079,004,01,38,02,24,07,01,00005V,...` |
| Oct 2017 onward | 4-digit year | `28,079,004,01,38,02,2024,01,01,00023V,...` |

For CSV format (used in `may_mo18.csv`), the year is always 4-digit regardless of period.

### 3.5 Daily data format

Same structure but with period code 04 instead of 02, columns D01–D31 (one per day of month) with V01–V31 validation flags. Row represents one station × one pollutant × one month.

---

## 4. Pollutant Codes — MAGNITUD (Annex II, verified)

| Code | Pollutant | Abbreviation | Unit | Technique Code | Measurement Technique | Present in may_mo18.csv |
|------|-----------|-------------|------|---------------|-----------------------|:-:|
| 1 | Sulphur dioxide | SO2 | µg/m³ | 38 | Ultraviolet fluorescence | ✓ |
| 6 | Carbon monoxide | CO | mg/m³ | 48 | Infrared absorption | ✓ |
| 7 | Nitrogen monoxide | NO | µg/m³ | 08 | Chemiluminescence | ✓ |
| 8 | Nitrogen dioxide | NO2 | µg/m³ | 08 | Chemiluminescence | ✓ |
| 9 | Particles < 2.5 µm | PM2.5 | µg/m³ | 47 | Microbalance/Spectrometry* | ✓ |
| 10 | Particles < 10 µm | PM10 | µg/m³ | 47 | Microbalance/Spectrometry* | ✓ |
| 12 | Nitrogen oxides | NOx | µg/m³ | 08 | Chemiluminescence | ✓ |
| 14 | Ozone | O3 | µg/m³ | 06 | Ultraviolet absorption | ✓ |
| 20 | Toluene | TOL | µg/m³ | 59 | Gas chromatography | ✓ |
| 30 | Benzene | BEN | µg/m³ | 59 | Gas chromatography | ✓ |
| 35 | Ethylbenzene | EBE | µg/m³ | 59 | Gas chromatography | ✓ |
| 37 | Meta-xylene | MXY | µg/m³ | 59 | Gas chromatography | — |
| 38 | Para-xylene | PXY | µg/m³ | 59 | Gas chromatography | — |
| 39 | Ortho-xylene | OXY | µg/m³ | 59 | Gas chromatography | — |
| 42 | Total hydrocarbons (hexane) | TCH | mg/m³ | 59 | Gas chromatography | ✓ |
| 43 | Methane | CH4 | mg/m³ | 59 | Gas chromatography | ✓ |
| 44 | Non-methane hydrocarbons (hexane) | NMHC | mg/m³ | 59 | Gas chromatography | ✓ |
| 431 | Meta-para-xylene | MPX | mg/m³ | 59 | Gas chromatography | — |

*Since 2024, two particle measurement techniques coexist: microbalance and optical aerosol spectrometry.

**Note on units:** Most pollutants use µg/m³. Exceptions: CO, TCH, CH4, NMHC, MPX use **mg/m³**. Be careful not to mix scales when normalizing for ML.

### Pollutant typical ranges and plausibility checks

| Pollutant | Normal Range | Flag if > | Known anomalies |
|-----------|-------------|-----------|-----------------|
| NO2 | 0–200 µg/m³ | 500 µg/m³ | — |
| PM10 | 0–150 µg/m³ | 300 µg/m³ | Saharan dust events (e.g. Feb 22, 2016) can push to 300+ |
| PM2.5 | 0–80 µg/m³ | 200 µg/m³ | — |
| O3 | 0–200 µg/m³ | 400 µg/m³ | Community reports of 7,100 µg/m³ (instrument error) |
| CO | 0–5 mg/m³ | 15 mg/m³ | — |

---

## 5. Validation Flags

| Flag | Meaning | Use in ML Pipeline |
|------|---------|--------------------|
| `V` | Validated (reviewed and approved) | Include in training set |
| `N` | Not validated (provisional, pending review) | Use cautiously; exclude from training, allow in real-time inference |
| *(blank/absent)* | No measurement recorded | Treat as NaN/missing |

**Why data may be missing** (from official PDF, Section 7):
- Equipment maintenance
- Anomalous readings reviewed and annulled during validation
- Power supply failures
- Communication failures
- Analyzer equipment malfunction (reading never recorded)

---

## 6. Air Quality Station Codes — Annex I (verified from official PDF)

### Currently active stations (24 total)

| Code | Name | Status | Notes |
|------|------|--------|-------|
| 28079004 | Pza. de España | Active | — |
| 28079008 | Escuelas Aguirre | Active | — |
| 28079011 | Av. Ramón y Cajal | Active | — |
| 28079016 | Arturo Soria | Active | — |
| 28079017 | Villaverde Alto | Active | — |
| 28079018 | C/ Farolillo | Active | — |
| 28079024 | Casa de Campo | Active | — |
| 28079027 | Barajas | Active | — |
| 28079035 | Pza. del Carmen | Active | *Since Jan 2010. Previous code: 28079003 |
| 28079036 | Moratalaz | Active | *Since Jan 2010. Previous code: 28079020 |
| 28079038 | Cuatro Caminos | Active | *Since Jan 2010. Previous code: 28079010 |
| 28079039 | Barrio del Pilar | Active | *Since Jan 2010. Previous code: 28079005 |
| 28079040 | Vallecas | Active | *Since Jan 2010. Previous code: 28079013 |
| 28079047 | Méndez Álvaro | Active since 21/12/2009 | — |
| 28079048 | Pº. Castellana | Active since 01/06/2010 | — |
| 28079049 | Retiro | Active since 01/01/2010 | — |
| 28079050 | Pza. Castilla | Active since 08/02/2010 | — |
| 28079054 | Ensanche Vallecas | Active since 11/12/2009 | — |
| 28079055 | Urb. Embajada (Barajas) | Active since 20/01/2010 | — |
| 28079056 | Plaza Elíptica | Active since 18/01/2010 | — |
| 28079057 | Sanchinarro | Active since 24/11/2009 | — |
| 28079058 | El Pardo | Active since 30/11/2009 | — |
| 28079059 | Parque Juan Carlos I | Active since 14/12/2009 | — |
| 28079060 | Tres Olivos | Active since 14/01/2010 | — |

### Decommissioned stations (not in current data)

| Code | Name | Decommissioned |
|------|------|---------------|
| 28079001 | Pº. Recoletos | 04/05/2009 |
| 28079002 | Glta. de Carlos V | 04/12/2006 |
| 28079006 | Pza. Dr. Marañón | 27/11/2009 |
| 28079007 | Pza. M. de Salamanca | 30/12/2009 |
| 28079009 | Pza. Luca de Tena | 07/12/2009 |
| 28079012 | Pza. Manuel Becerra | 30/12/2009 |
| 28079014 | Pza. Fdez. Ladreda | 02/12/2009 |
| 28079015 | Pza. Castilla (old) | 17/10/2008 |
| 28079019 | Huerta Castañeda | 30/12/2009 |
| 28079021 | Pza. Cristo Rey | 04/12/2009 |
| 28079022 | Pº. Pontones | 20/11/2009 |
| 28079023 | Final C/ Alcalá | 30/12/2009 |
| 28079025 | Santa Eugenia | 16/11/2009 |
| 28079026 | Urb. Embajada (old) | 11/01/2010 |

**Code migration note:** Four stations changed codes in January 2010 for national data exchange standardization. Historical data before 2010 uses the old codes (3→35, 5→39, 10→38, 13→40, 20→36). The ingestion pipeline must map old codes to new when processing pre-2010 files.

### Station types

- **Tráfico:** Near major roads, pollution dominated by vehicle emissions. Best candidates for pairing with traffic counters.
- **Fondo urbano (urban background):** Representative of general population exposure. Not directly tied to specific roads.
- **Suburbana:** City outskirts, mainly for O3 monitoring.

### Stations observed in `may_mo18.csv` (May 2018)

24 unique ESTACION values: 4, 8, 11, 16, 17, 18, 24, 27, 35, 36, 38, 39, 40, 47, 48, 49, 50, 54, 55, 56, 57, 58, 59, 60.

Not all stations measure all pollutants. Station 4 (Pza. de España) measures SO2, CO, NO, NO2, NOx. Station 8 (Escuelas Aguirre) additionally measures PM2.5, PM10, O3, Benzene, Toluene, Ethylbenzene, and hydrocarbons.

---

## 7. Air Quality Station Metadata (A4)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| Station code | integer | Matches ESTACION in A1 | `4` |
| Full code | string | Province + Municipality + Station | `28079004` |
| Station name | string | Location name | `Pza. de España` |
| Station type | string | Classification | `Tráfico` / `Fondo urbano` / `Suburbana` |
| Latitude | float | WGS84, decimal degrees | `40.4238823` |
| Longitude | float | WGS84, decimal degrees | `-3.7122567` |
| Pollutants measured | list | Active analyzers | `NO, NO2, PM10, PM2.5, O3` |
| Operational since | date | Start of operation | `2010-01-01` |

---

## 8. Meteorological Hourly (W1)

**Source:** Comunidad de Madrid CKAN — yearly CSVs from 2019/2020 onward.

| Field | Type | Unit | Description | Typical Range |
|-------|------|------|-------------|---------------|
| Station | string | — | Weather station ID | — |
| Date | datetime | — | Timestamp (local time) | — |
| Wind speed | float | m/s | Hourly mean | 0–15 |
| Wind direction | float | degrees | 0=N, 90=E, 180=S, 270=W | 0–360 |
| Temperature | float | °C | Hourly mean | -5 to 42 |
| Relative humidity | float | % | Hourly mean | 10–100 |
| Atmospheric pressure | float | hPa | Hourly mean | 920–1040 |
| Solar radiation | float | W/m² | Hourly mean | 0–1000 |
| Precipitation | float | mm | Hourly accumulated | 0–50 |

---

## 9. Target Schemas (After Ingestion Pipeline)

### traffic_hourly.parquet

| Column | Type | Description |
|--------|------|-------------|
| datetime | datetime64[ns, Europe/Madrid] | Hourly timestamp |
| station_id | string | Station ID (e.g. ES01) |
| direction | int | 1 or 2 (0 if single-direction) |
| vehicles | int | Vehicle count for this hour |
| lat | float | Station latitude |
| lon | float | Station longitude |

### air_quality_hourly.parquet

| Column | Type | Description |
|--------|------|-------------|
| datetime | datetime64[ns, Europe/Madrid] | Hourly timestamp |
| station_id | int | Station code (e.g. 4, 8, 47) |
| station_type | string | trafico / fondo_urbano / suburbana |
| NO2 | float | µg/m³ (NaN if missing) |
| PM10 | float | µg/m³ |
| PM25 | float | µg/m³ |
| NO | float | µg/m³ |
| CO | float | mg/m³ |
| O3 | float | µg/m³ |
| SO2 | float | µg/m³ |
| NOx | float | µg/m³ |
| validated | bool | True if all values in row are V-flagged |
| lat | float | Station latitude |
| lon | float | Station longitude |

### weather_hourly.parquet

| Column | Type | Description |
|--------|------|-------------|
| datetime | datetime64[ns, Europe/Madrid] | Hourly timestamp |
| station_id | string | Weather station ID |
| temperature | float | °C |
| wind_speed | float | m/s |
| wind_direction | float | degrees |
| humidity | float | % |
| pressure | float | hPa |
| precipitation | float | mm |
| solar_radiation | float | W/m² |

### station_pairs.csv

| Column | Type | Description |
|--------|------|-------------|
| pair_id | string | Unique pair identifier |
| traffic_station | string | Traffic station ID (e.g. ES47) |
| aq_station | int | Air quality station code (e.g. 47) |
| distance_m | float | Haversine distance in meters |
| aq_station_type | string | Type of air quality station |
| tier | string | 500m / 1km / 2km |

---

## 10. Mapping Quick Reference — MAGNITUD → Pollutant Python Dict

```python
MAGNITUD_MAP = {
    1:  ("SO2",  "µg/m³", 38, "Ultraviolet fluorescence"),
    6:  ("CO",   "mg/m³", 48, "Infrared absorption"),
    7:  ("NO",   "µg/m³",  8, "Chemiluminescence"),
    8:  ("NO2",  "µg/m³",  8, "Chemiluminescence"),
    9:  ("PM25", "µg/m³", 47, "Microbalance/Spectrometry"),
    10: ("PM10", "µg/m³", 47, "Microbalance/Spectrometry"),
    12: ("NOx",  "µg/m³",  8, "Chemiluminescence"),
    14: ("O3",   "µg/m³",  6, "Ultraviolet absorption"),
    20: ("TOL",  "µg/m³", 59, "Gas chromatography"),
    30: ("BEN",  "µg/m³", 59, "Gas chromatography"),
    35: ("EBE",  "µg/m³", 59, "Gas chromatography"),
    37: ("MXY",  "µg/m³", 59, "Gas chromatography"),
    38: ("PXY",  "µg/m³", 59, "Gas chromatography"),
    39: ("OXY",  "µg/m³", 59, "Gas chromatography"),
    42: ("TCH",  "mg/m³", 59, "Gas chromatography"),
    43: ("CH4",  "mg/m³", 59, "Gas chromatography"),
    44: ("NMHC", "mg/m³", 59, "Gas chromatography"),
    431:("MPX",  "mg/m³", 59, "Gas chromatography"),
}
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| v1 | 2026-02-25 | Initial data dictionary from catalog inspection |
| v2 | 2026-02-25 | Verified against real `may_mo18.csv` (4,650 rows, 24 stations, 14 pollutants). Added PUNTO_MUESTREO decoding. Added complete station code annex from official PDF (24 active + 14 decommissioned). Added DST handling rules from official PDF Notes section. Added technique codes per pollutant. Confirmed H01=1AM / H24=midnight convention. Documented pre/post Oct 2017 year format change. Added unit warnings (µg/m³ vs mg/m³). Added worked traffic example from real April 2018 data. Added plausibility check thresholds. |
