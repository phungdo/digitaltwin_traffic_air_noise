# Digital Twin: Traffic Prediction from Air Quality & Noise

Barcelona urban sensing data analysis: spatial matching, hourly aggregation, and ML/DL correlation between **traffic congestion**, **noise levels**, and **air quality**.

## Barcelona Analysis Pipeline

### 1. Spatial Matching
| Script | Description | Output |
|--------|-------------|--------|
| `match_traffic_noise.py` | Match traffic sections ↔ noise sensors (200m) | 790 pairs |
| `match_traffic_airquality.py` | Match traffic sections ↔ air quality stations (500m) | 100 pairs |

### 2. Hourly Aggregation
| Script | Method |
|--------|--------|
| `aggregate_hourly.py` | Noise: energy-averaged LAeq, Traffic: mode/mean, Air: wide→long reshape |

### 3. ML/DL Correlation Analysis
| Script | Models |
|--------|--------|
| `ml_correlation_analysis.py` | Pearson/Spearman, Random Forest, LSTM (PyTorch) |

**Key Results:**
- Traffic ↔ Noise: Pearson r = 0.295 (aggregate), r = 0.662 (best pair)
- LSTM (paper TABLE I features): R² = 0.612, MAE = 0.439
- Air Pollution ↔ Noise: NO r = 0.44 (Eixample), NOx r = 0.42 (Gràcia)

### 4. Output Files
```
barcelona/
├── Scripts
│   ├── match_traffic_noise.py
│   ├── match_traffic_airquality.py
│   ├── aggregate_hourly.py
│   └── ml_correlation_analysis.py
├── Spatial Matching Results
│   ├── matched_traffic_noise_pairs.csv
│   ├── matched_traffic_airquality_pairs.csv
│   └── matched_air_noise_pairs.csv
├── Aggregated Hourly Data
│   ├── noise_hourly.csv
│   ├── traffic_trams_hourly.csv
│   ├── traffic_itineraris_hourly.csv
│   └── air_quality_hourly.csv
├── Visualizations
│   ├── fig4_traffic_noise_hourly_correlation.png
│   ├── fig4_multi_sensor_comparison.png
│   ├── matched_traffic_noise_map.png
│   ├── matched_traffic_airquality_map.png
│   └── combined_traffic_air_noise_map.png
└── ml_results/
    ├── phase2_correlation.png
    ├── phase2_heatmap.png
    ├── phase3_random_forest.png
    ├── phase4_lstm.png
    ├── air_noise_heatmap.png
    ├── air_noise_hourly_profiles.png
    ├── air_noise_scatter.png
    └── correlation_*.csv
```

## Data Sources (Barcelona Open Data)

Raw data files are excluded from this repo due to size. Download from:
- **Traffic:** [Trànsit - Dades de Trams](https://opendata-ajuntament.barcelona.cat/)
- **Noise:** [Xarxa de Soroll - Dades 1 Minut](https://opendata-ajuntament.barcelona.cat/)
- **Air Quality:** [Qualitat de l'Aire - BCN](https://opendata-ajuntament.barcelona.cat/)

## Requirements

```bash
pip install pandas geopandas shapely matplotlib contextily scipy scikit-learn seaborn torch
```

## Reference

Based on methodology from: *"Using Noise Pollution Data for Traffic Prediction in Smart Cities: Experiments Based on LSTM Recurrent Neural Networks"*
