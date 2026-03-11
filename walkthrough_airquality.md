# Walkthrough: Air Quality Data Ingestion Script

## What Was Built

Created [download_madrid_airquality.py](file:///Users/Apple/Downloads/madrid_traffic_airquality/airquality_dataset/download_madrid_airquality.py) — an ingestion script that downloads monthly air quality CSV data (2018–2025) from the Madrid Open Data portal.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Hardcoded resource IDs | URLs are stable; avoids fragile HTML scraping |
| ZIP extraction for 2018–2024 | Portal provides yearly ZIP archives; script extracts & renames CSVs |
| CSV splitting for 2025 | Portal provides a single CSV; script splits by `MES` column |
| `--dry-run` flag | Allows verification without downloading |

## Output File Naming

Files are saved as `YYYY_Mon.csv` in `~/Downloads/madrid_traffic_airquality/airquality_dataset/`:

```
2018_Jan.csv, 2018_Feb.csv, ..., 2018_Dec.csv
2019_Jan.csv, 2019_Feb.csv, ..., 2019_Dec.csv
...
2025_Jan.csv, 2025_Feb.csv, ...
```

## Usage

```bash
# Full download (all years)
python3 download_madrid_airquality.py

# Dry-run (show URLs without downloading)
python3 download_madrid_airquality.py --dry-run

# Single year only
python3 download_madrid_airquality.py --year 2024
```

> [!NOTE]
> Requires the `requests` package: `pip install requests`

## Verification

Dry-run test passed with all 8 years configured correctly:

```
2026-02-25 16:58:07 | INFO     | Madrid Air Quality – Hourly CSV Downloader
2026-02-25 16:58:07 | INFO     | *** DRY-RUN MODE – no files will be downloaded ***
  Processing year 2018 ... [DRY-RUN] Would download: .../201200-18-calidad-aire-horario-zip.zip
  Processing year 2019 ... [DRY-RUN] Would download: .../201200-6-calidad-aire-horario-zip.zip
  ...
  Processing year 2025 ... [DRY-RUN] Would download: .../201200-1-calidad-aire-horario-csv.csv
Download complete in 8.0 seconds.
  Downloaded: 0 | Skipped: 0 | Failed: 0 | Invalid: 0
```
