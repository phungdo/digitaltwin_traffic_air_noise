#!/usr/bin/env python3
"""
Barcelona: ML/DL Correlation Analysis
=======================================
Finds correlations between traffic congestion, noise levels, and air quality
using statistical analysis, Random Forest, and LSTM deep learning.

Pipeline:
  Phase 1 — Data merging (via spatial matching tables)
  Phase 2 — Statistical correlation (Pearson, Spearman)
  Phase 3 — Random Forest feature importance
  Phase 4 — LSTM time-series model (predict traffic from noise + air quality)

Requirements:
    pip install pandas numpy scikit-learn scipy seaborn matplotlib torch
"""

import warnings
warnings.filterwarnings("ignore")

import sys
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (mean_absolute_error, mean_squared_error, r2_score,
                             classification_report, accuracy_score)

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DIR = SCRIPT_DIR / "ml_results"
OUT_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# PHASE 1: Data merging
# ═══════════════════════════════════════════════════════════════════
def load_and_merge():
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  PHASE 1: Data Merging                                      ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    # Load hourly data
    noise = pd.read_csv(SCRIPT_DIR / "noise_hourly.csv", parse_dates=["hour"])
    traffic = pd.read_csv(SCRIPT_DIR / "traffic_trams_hourly.csv", parse_dates=["hour"])
    air = pd.read_csv(SCRIPT_DIR / "air_quality_hourly.csv", parse_dates=["hour"])

    # Load spatial matching tables
    match_tn = pd.read_csv(SCRIPT_DIR / "matched_traffic_noise_pairs.csv")
    match_ta = pd.read_csv(SCRIPT_DIR / "matched_traffic_airquality_pairs.csv")

    print(f"  Noise hourly:    {len(noise):>8,} rows  ({noise['Id_Instal'].nunique()} sensors)")
    print(f"  Traffic hourly:  {len(traffic):>8,} rows  ({traffic['idTram'].nunique()} sections)")
    print(f"  Air hourly:      {len(air):>8,} rows  ({air['Estacio'].nunique()} stations)")
    print(f"  Match TN:        {len(match_tn):>8,} pairs")
    print(f"  Match TA:        {len(match_ta):>8,} pairs")

    # ── A: Traffic ↔ Noise merge ──
    # Use only matched pairs with active measurements
    tn_pairs = match_tn[match_tn["has_measurements"] == True][
        ["Id_Instal", "idTram", "distance_m"]
    ].drop_duplicates()
    # Keep closest traffic section per noise sensor
    tn_pairs = tn_pairs.sort_values("distance_m").drop_duplicates(subset=["Id_Instal"], keep="first")
    print(f"\n  Active noise↔traffic pairs: {len(tn_pairs)}")

    # Merge noise + traffic via matching table
    tn_merged = (
        noise.merge(tn_pairs, on="Id_Instal", how="inner")
        .merge(traffic, on=["idTram", "hour"], how="inner",
               suffixes=("_noise", "_traffic"))
    )
    print(f"  Traffic↔Noise merged: {len(tn_merged):,} rows")

    # ── B: Traffic ↔ Air merge ──
    # Pivot air quality: one column per contaminant
    # Focus on main pollutants (codes < 100)
    air_main = air[air["Codi_Contaminant"] < 100].copy()
    air_pivot = air_main.pivot_table(
        index=["Estacio", "hour"], columns="contaminant",
        values="value", aggfunc="first"
    ).reset_index()
    air_pivot.columns.name = None

    # Use closest traffic section per station
    ta_pairs = match_ta[["Estacio", "idTram", "distance_m"]].copy()
    ta_pairs = ta_pairs.sort_values("distance_m").drop_duplicates(subset=["Estacio"], keep="first")
    print(f"  Air↔traffic pairs (closest): {len(ta_pairs)}")

    ta_merged = (
        air_pivot.merge(ta_pairs, on="Estacio", how="inner")
        .merge(traffic, on=["idTram", "hour"], how="inner")
    )
    print(f"  Traffic↔Air merged: {len(ta_merged):,} rows")

    # ── C: Three-way merge (traffic sections near BOTH noise + air) ──
    # Find traffic sections that appear in both matching tables
    common_trams = set(tn_pairs["idTram"]) & set(ta_pairs["idTram"])
    print(f"\n  Traffic sections near both noise + air: {len(common_trams)}")

    if len(common_trams) > 0:
        # For three-way: merge traffic + noise + air via common tram
        three_way = tn_merged[tn_merged["idTram"].isin(common_trams)].copy()
        # Add air quality by matching hour and finding nearest station
        # Map each tram to its nearest air station
        tram_to_station = ta_pairs[ta_pairs["idTram"].isin(common_trams)][
            ["idTram", "Estacio"]
        ]
        three_way = three_way.merge(tram_to_station, on="idTram", how="left")
        three_way = three_way.merge(
            air_pivot, on=["Estacio", "hour"], how="left"
        )
        three_way = three_way.dropna(subset=["LAeq_1h", "estatActual_mean"])
        print(f"  Three-way merged: {len(three_way):,} rows")
    else:
        three_way = pd.DataFrame()
        print("  ⚠ No three-way overlap found (noise sensors not near air stations)")

    # Add time features
    for df in [tn_merged, ta_merged, three_way]:
        if len(df) > 0 and "hour" in df.columns:
            df["hour_of_day"] = df["hour"].dt.hour
            df["day_of_week"] = df["hour"].dt.dayofweek
            df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)

    return tn_merged, ta_merged, three_way


# ═══════════════════════════════════════════════════════════════════
# PHASE 2: Statistical correlation
# ═══════════════════════════════════════════════════════════════════
def statistical_correlation(tn_merged, ta_merged, three_way):
    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║  PHASE 2: Statistical Correlation                           ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    fig, axes = plt.subplots(1, 3, figsize=(20, 6))

    # ── 2A: Traffic state vs Noise level ──
    print("  ── Traffic ↔ Noise ──")
    cols_tn = ["LAeq_1h", "estatActual_mean", "hour_of_day", "is_weekend"]
    df_tn = tn_merged[cols_tn].dropna()
    if len(df_tn) > 0:
        r_p, p_p = stats.pearsonr(df_tn["estatActual_mean"], df_tn["LAeq_1h"])
        r_s, p_s = stats.spearmanr(df_tn["estatActual_mean"], df_tn["LAeq_1h"])
        print(f"    Pearson:  r={r_p:.4f}, p={p_p:.2e}")
        print(f"    Spearman: r={r_s:.4f}, p={p_s:.2e}")

        # Heatmap by hour
        hour_corr = tn_merged.groupby("hour_of_day").apply(
            lambda g: g["estatActual_mean"].corr(g["LAeq_1h"]),
            include_groups=False
        )
        print(f"    Correlation by hour: min={hour_corr.min():.3f}, max={hour_corr.max():.3f}")

        # Scatter
        sample = df_tn.sample(min(5000, len(df_tn)), random_state=42)
        axes[0].scatter(sample["estatActual_mean"], sample["LAeq_1h"],
                       alpha=0.15, s=5, c=sample["hour_of_day"], cmap="viridis")
        axes[0].set_xlabel("Traffic State (mean)")
        axes[0].set_ylabel("Noise LAeq 1h (dB)")
        axes[0].set_title(f"Traffic ↔ Noise\nPearson r={r_p:.3f}, Spearman ρ={r_s:.3f}")

    # ── 2B: Traffic state vs Air quality ──
    print("\n  ── Traffic ↔ Air Quality ──")
    pollutants = [c for c in ta_merged.columns
                  if c not in ["Estacio", "hour", "idTram", "distance_m",
                               "estatActual_mode", "estatActual_mean",
                               "estatPrevist_mode", "n_samples",
                               "hour_of_day", "day_of_week", "is_weekend"]]
    corr_results = []
    for pol in pollutants:
        df_temp = ta_merged[["estatActual_mean", pol]].dropna()
        if len(df_temp) > 30:
            r, p = stats.pearsonr(df_temp["estatActual_mean"], df_temp[pol])
            rs, ps = stats.spearmanr(df_temp["estatActual_mean"], df_temp[pol])
            corr_results.append({"pollutant": pol, "pearson_r": r, "pearson_p": p,
                                "spearman_r": rs, "spearman_p": ps, "n": len(df_temp)})
            print(f"    {pol:15s}  Pearson r={r:+.4f} (p={p:.2e})  Spearman ρ={rs:+.4f}")

    if corr_results:
        corr_df = pd.DataFrame(corr_results).sort_values("pearson_r", key=abs, ascending=False)
        corr_df.to_csv(OUT_DIR / "correlation_traffic_air.csv", index=False)

        # Bar chart
        corr_df_plot = corr_df.head(10)
        colors = ["#ff4444" if r > 0 else "#3388ff" for r in corr_df_plot["pearson_r"]]
        axes[1].barh(corr_df_plot["pollutant"], corr_df_plot["pearson_r"], color=colors)
        axes[1].set_xlabel("Pearson r")
        axes[1].set_title("Traffic ↔ Air Quality\nCorrelation per Pollutant")
        axes[1].axvline(0, color="black", linewidth=0.5)

    # ── 2C: Correlation by hour of day ──
    print("\n  ── Correlation by hour of day ──")
    if len(tn_merged) > 0:
        hourly_corr = []
        for h in range(24):
            subset = tn_merged[tn_merged["hour_of_day"] == h]
            if len(subset) > 30:
                r, _ = stats.pearsonr(subset["estatActual_mean"], subset["LAeq_1h"])
                hourly_corr.append({"hour": h, "pearson_r": r})
        if hourly_corr:
            hc = pd.DataFrame(hourly_corr)
            axes[2].bar(hc["hour"], hc["pearson_r"],
                       color=["#ff8800" if r > 0 else "#3388ff" for r in hc["pearson_r"]])
            axes[2].set_xlabel("Hour of Day")
            axes[2].set_ylabel("Pearson r (Traffic↔Noise)")
            axes[2].set_title("Traffic↔Noise Correlation\nby Hour of Day")
            axes[2].set_xticks(range(0, 24, 2))
            axes[2].axhline(0, color="black", linewidth=0.5)

    plt.tight_layout()
    plt.savefig(OUT_DIR / "phase2_correlation.png", dpi=150)
    plt.close()
    print(f"\n  ✓ Saved: phase2_correlation.png")

    # Full correlation matrix heatmap
    _correlation_heatmap(tn_merged, ta_merged)


def _correlation_heatmap(tn_merged, ta_merged):
    """Generate heatmap of all numeric correlations."""
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))

    # Traffic ↔ Noise
    cols = ["LAeq_1h", "estatActual_mean", "hour_of_day", "is_weekend", "n_samples_noise"]
    available = [c for c in cols if c in tn_merged.columns]
    if available:
        corr = tn_merged[available].corr()
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
                    ax=axes[0], vmin=-1, vmax=1, square=True)
        axes[0].set_title("Traffic ↔ Noise", fontweight="bold")

    # Traffic ↔ Air
    exclude = {"Estacio", "hour", "idTram", "distance_m", "estatActual_mode",
               "estatPrevist_mode", "day_of_week"}
    num_cols = [c for c in ta_merged.select_dtypes(include=[np.number]).columns
                if c not in exclude]
    if num_cols:
        corr = ta_merged[num_cols].corr()
        sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0,
                    ax=axes[1], vmin=-1, vmax=1, square=True,
                    annot_kws={"size": 7})
        axes[1].set_title("Traffic ↔ Air Quality", fontweight="bold")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "phase2_heatmap.png", dpi=150)
    plt.close()
    print(f"  ✓ Saved: phase2_heatmap.png")


# ═══════════════════════════════════════════════════════════════════
# PHASE 3: Random Forest feature importance
# ═══════════════════════════════════════════════════════════════════
def random_forest_analysis(tn_merged, ta_merged):
    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║  PHASE 3: Random Forest Feature Importance                  ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # ── 3A: Predict traffic state from noise + time features ──
    print("  ── Predict traffic state from noise ──")
    features_tn = ["LAeq_1h", "hour_of_day", "day_of_week", "is_weekend"]
    df_tn = tn_merged[features_tn + ["estatActual_mean"]].dropna()

    if len(df_tn) > 100:
        X = df_tn[features_tn]
        y = df_tn["estatActual_mean"]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        rf = RandomForestRegressor(n_estimators=200, max_depth=15,
                                   random_state=42, n_jobs=-1)
        rf.fit(X_train, y_train)
        y_pred = rf.predict(X_test)

        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        print(f"    MAE:  {mae:.4f}")
        print(f"    RMSE: {rmse:.4f}")
        print(f"    R²:   {r2:.4f}")

        # Feature importance
        imp = pd.Series(rf.feature_importances_, index=features_tn).sort_values()
        imp.plot(kind="barh", ax=axes[0], color="#ff8800")
        axes[0].set_title(f"Predict Traffic from Noise\nR²={r2:.3f}, RMSE={rmse:.3f}")
        axes[0].set_xlabel("Feature Importance")

    # ── 3B: Predict traffic state from air quality + time features ──
    print("\n  ── Predict traffic state from air quality ──")
    pollutants = [c for c in ta_merged.columns
                  if c not in {"Estacio", "hour", "idTram", "distance_m",
                               "estatActual_mode", "estatActual_mean",
                               "estatPrevist_mode", "n_samples",
                               "hour_of_day", "day_of_week", "is_weekend"}
                  and ta_merged[c].dtype in [np.float64, np.int64]]
    features_ta = pollutants + ["hour_of_day", "day_of_week", "is_weekend"]
    df_ta = ta_merged[features_ta + ["estatActual_mean"]].dropna()

    if len(df_ta) > 100:
        X = df_ta[features_ta]
        y = df_ta["estatActual_mean"]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        rf = RandomForestRegressor(n_estimators=200, max_depth=15,
                                   random_state=42, n_jobs=-1)
        rf.fit(X_train, y_train)
        y_pred = rf.predict(X_test)

        mae = mean_absolute_error(y_test, y_pred)
        rmse = np.sqrt(mean_squared_error(y_test, y_pred))
        r2 = r2_score(y_test, y_pred)
        print(f"    MAE:  {mae:.4f}")
        print(f"    RMSE: {rmse:.4f}")
        print(f"    R²:   {r2:.4f}")

        imp = pd.Series(rf.feature_importances_, index=features_ta).sort_values()
        imp.plot(kind="barh", ax=axes[1], color="#3388ff")
        axes[1].set_title(f"Predict Traffic from Air Quality\nR²={r2:.3f}, RMSE={rmse:.3f}")
        axes[1].set_xlabel("Feature Importance")

    plt.tight_layout()
    plt.savefig(OUT_DIR / "phase3_random_forest.png", dpi=150)
    plt.close()
    print(f"\n  ✓ Saved: phase3_random_forest.png")


# ═══════════════════════════════════════════════════════════════════
# PHASE 4: LSTM Time-Series Model
# ═══════════════════════════════════════════════════════════════════
class TrafficLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        lstm_out, _ = self.lstm(x)
        return self.fc(lstm_out[:, -1, :])


def create_sequences(data, seq_length=24):
    """Create sliding window sequences for LSTM."""
    X, y = [], []
    for i in range(len(data) - seq_length):
        X.append(data[i:i + seq_length, :-1])  # features
        y.append(data[i + seq_length, -1])       # target (next hour)
    return np.array(X), np.array(y)


def lstm_analysis(tn_merged, ta_merged):
    """
    LSTM matching the paper's TABLE I:
      Features: Hour (0-23), Week Day (0-6), Noise (dBA)
      Target:   Traffic (state, analogous to vehicles/hour)
    """
    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║  PHASE 4: LSTM Time-Series Model                            ║")
    print("║  (Matching paper TABLE I features)                           ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    print("  Features used (matching paper TABLE I):")
    print("  ┌──────────────┬────────────────────┐")
    print("  │ Feature      │ Values/Unit        │")
    print("  ├──────────────┼────────────────────┤")
    print("  │ Hour         │ 0-23               │")
    print("  │ Week Day     │ 0-6                │")
    print("  │ Noise        │ dBA (LAeq_1h)      │")
    print("  │ Traffic *    │ State 0-6 (target)  │")
    print("  └──────────────┴────────────────────┘")
    print("  * Paper uses vehicles/hour; our data has state (0=free, 6=jam)\n")

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"  Device: {device}")

    results = {}

    # ── Use the best sensor-tram pair (like the paper: single pair) ──
    # Sensor 1196 (Sant Joan, Eixample, TRÀNSIT) ↔ Section 197
    BEST_SENSOR = 1196
    BEST_TRAM = 197
    SENSOR_DESC = "Sensor 1196 (Sant Joan, Eixample)"
    TRAM_DESC = "Section 197 (Psg. Sant Joan)"

    print(f"\n  ── Single-pair LSTM (like the paper) ──")
    print(f"  Noise:   {SENSOR_DESC}")
    print(f"  Traffic: {TRAM_DESC}")

    subset = tn_merged[
        (tn_merged["Id_Instal"] == BEST_SENSOR) &
        (tn_merged["idTram"] == BEST_TRAM)
    ].sort_values("hour").copy()

    print(f"  Data points: {len(subset)} hours")

    if len(subset) < 100:
        print("  ⚠ Not enough data for this pair, trying top pairs...")
        # Fallback: use top pairs by data count
        pair_counts = tn_merged.groupby(["Id_Instal", "idTram"]).size().reset_index(name="count")
        pair_counts = pair_counts.sort_values("count", ascending=False)
        top = pair_counts.iloc[0]
        subset = tn_merged[
            (tn_merged["Id_Instal"] == top["Id_Instal"]) &
            (tn_merged["idTram"] == top["idTram"])
        ].sort_values("hour").copy()
        print(f"  Using Sensor {top['Id_Instal']} ↔ Section {top['idTram']} ({len(subset)} hours)")

    # ── Features matching TABLE I ──
    # Column order: [Hour, Week Day, Noise, Traffic(target)]
    FEATURE_COLS = ["hour_of_day", "day_of_week", "LAeq_1h"]
    TARGET_COL = "estatActual_mean"

    series = subset[FEATURE_COLS + [TARGET_COL]].dropna()
    data = series.values
    print(f"  Clean data: {len(data)} timesteps")
    print(f"  Feature columns: {FEATURE_COLS}")
    print(f"  Target column: {TARGET_COL}")

    # Scale
    scaler = StandardScaler()
    scaled = scaler.fit_transform(data)

    # Create sequences (24-hour lookback, like the paper)
    SEQ_LEN = 24
    X, y = create_sequences(scaled, SEQ_LEN)
    print(f"  Sequences: {X.shape[0]} samples, lookback={SEQ_LEN}h")
    print(f"  Input shape: ({X.shape[0]}, {X.shape[1]}, {X.shape[2]})  "
          f"= (samples, timesteps, features)")

    if len(X) < 50:
        print("  ⚠ Not enough sequences")
        return results

    # 80/20 chronological split
    split = int(0.8 * len(X))
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]
    print(f"  Train: {len(X_train)} | Test: {len(X_test)}")

    # To tensors
    X_train_t = torch.FloatTensor(X_train).to(device)
    y_train_t = torch.FloatTensor(y_train).unsqueeze(1).to(device)
    X_test_t = torch.FloatTensor(X_test).to(device)
    y_test_t = torch.FloatTensor(y_test).unsqueeze(1).to(device)

    train_ds = TensorDataset(X_train_t, y_train_t)
    train_loader = DataLoader(train_ds, batch_size=32, shuffle=True)

    # Model — matching paper architecture
    input_size = X.shape[2]  # 3 features: hour, weekday, noise
    model = TrafficLSTM(input_size=input_size, hidden_size=64, num_layers=2).to(device)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)

    print(f"\n  Model: LSTM(input={input_size}, hidden=64, layers=2) + FC(64→32→1)")
    print(f"  Parameters: {sum(p.numel() for p in model.parameters()):,}")

    # Train
    EPOCHS = 100
    train_losses, val_losses = [], []
    best_val_loss = float("inf")
    best_state = None
    print(f"  Training ({EPOCHS} epochs)...\n")

    for epoch in range(EPOCHS):
        model.train()
        epoch_loss = 0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            output = model(batch_X)
            loss = criterion(output, batch_y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            epoch_loss += loss.item()

        train_loss = epoch_loss / len(train_loader)
        train_losses.append(train_loss)

        model.eval()
        with torch.no_grad():
            val_pred = model(X_test_t)
            val_loss = criterion(val_pred, y_test_t).item()
        val_losses.append(val_loss)
        scheduler.step(val_loss)

        # Save best model
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if (epoch + 1) % 20 == 0:
            print(f"    Epoch {epoch+1:3d}/{EPOCHS}: "
                  f"train={train_loss:.4f}, val={val_loss:.4f}")

    # Load best model
    if best_state:
        model.load_state_dict({k: v.to(device) for k, v in best_state.items()})

    # Evaluate
    model.eval()
    with torch.no_grad():
        y_pred_scaled = model(X_test_t).cpu().numpy().flatten()

    # Inverse scale the target (last column)
    n_features = data.shape[1]
    dummy = np.zeros((len(y_test), n_features))
    dummy[:, -1] = y_test
    y_test_orig = scaler.inverse_transform(dummy)[:, -1]

    dummy[:, -1] = y_pred_scaled
    y_pred_orig = scaler.inverse_transform(dummy)[:, -1]

    mae = mean_absolute_error(y_test_orig, y_pred_orig)
    rmse = np.sqrt(mean_squared_error(y_test_orig, y_pred_orig))
    r2 = r2_score(y_test_orig, y_pred_orig)

    print(f"\n  ┌────────────────────────────────────┐")
    print(f"  │ LSTM Results (single pair)         │")
    print(f"  ├────────────────────────────────────┤")
    print(f"  │ MAE:  {mae:.4f}                    │")
    print(f"  │ RMSE: {rmse:.4f}                    │")
    print(f"  │ R²:   {r2:.4f}                    │")
    print(f"  └────────────────────────────────────┘")

    results["lstm_single_pair"] = {"mae": mae, "rmse": rmse, "r2": r2,
                                    "sensor": BEST_SENSOR, "tram": BEST_TRAM}

    # ── Plot LSTM results ──
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # Training curve
    axes[0, 0].plot(train_losses, label="Train", color="#3388ff")
    axes[0, 0].plot(val_losses, label="Validation", color="#ff4444")
    axes[0, 0].set_xlabel("Epoch")
    axes[0, 0].set_ylabel("MSE Loss")
    axes[0, 0].set_title("LSTM Training Curve")
    axes[0, 0].legend()

    # Prediction vs actual (time series)
    n_show = min(200, len(y_test_orig))
    axes[0, 1].plot(range(n_show), y_test_orig[:n_show],
                    label="Actual", alpha=0.8, color="#333", linewidth=1.5)
    axes[0, 1].plot(range(n_show), y_pred_orig[:n_show],
                    label="Predicted", alpha=0.8, color="#ff4444", linewidth=1.5)
    axes[0, 1].set_xlabel("Hours")
    axes[0, 1].set_ylabel("Traffic State")
    axes[0, 1].set_title(f"LSTM: Actual vs Predicted Traffic\n"
                         f"Sensor {BEST_SENSOR} → Section {BEST_TRAM} (R²={r2:.3f})")
    axes[0, 1].legend()

    # Scatter: predicted vs actual
    axes[1, 0].scatter(y_test_orig, y_pred_orig, alpha=0.3, s=15, color="#3388ff")
    lims = [min(y_test_orig.min(), y_pred_orig.min()),
            max(y_test_orig.max(), y_pred_orig.max())]
    axes[1, 0].plot(lims, lims, "--", color="#999", linewidth=1)
    axes[1, 0].set_xlabel("Actual Traffic State")
    axes[1, 0].set_ylabel("Predicted Traffic State")
    axes[1, 0].set_title(f"Prediction Scatter\nMAE={mae:.3f}, RMSE={rmse:.3f}")

    # Residuals
    residuals = y_test_orig - y_pred_orig
    axes[1, 1].hist(residuals, bins=40, color="#ff8800", alpha=0.7, edgecolor="white")
    axes[1, 1].axvline(0, color="black", linewidth=1)
    axes[1, 1].set_xlabel("Residual (Actual - Predicted)")
    axes[1, 1].set_ylabel("Count")
    axes[1, 1].set_title(f"Residual Distribution\n"
                         f"Mean={residuals.mean():.3f}, Std={residuals.std():.3f}")

    plt.suptitle(f"LSTM: Predict Traffic from Noise (Paper TABLE I features)\n"
                 f"Features: [Hour, Week Day, Noise] → Target: Traffic State",
                 fontsize=14, fontweight="bold")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "phase4_lstm.png", dpi=150)
    plt.close()
    print(f"  ✓ Saved: phase4_lstm.png")

    return results


# ═══════════════════════════════════════════════════════════════════
# PHASE 5: Summary report
# ═══════════════════════════════════════════════════════════════════
def write_summary(lstm_results):
    print("\n╔═══════════════════════════════════════════════════════════════╗")
    print("║  SUMMARY                                                    ║")
    print("╚═══════════════════════════════════════════════════════════════╝")
    print(f"""
    Output files in: {OUT_DIR.name}/
    ├── phase2_correlation.png     — scatter + bar charts
    ├── phase2_heatmap.png         — full correlation matrix
    ├── phase3_random_forest.png   — feature importance
    ├── phase4_lstm.png            — LSTM training + predictions
    └── correlation_traffic_air.csv — per-pollutant correlations
    """)


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main():
    print("╔═══════════════════════════════════════════════════════════════╗")
    print("║  Barcelona: ML/DL Correlation Analysis                      ║")
    print("║  Traffic ↔ Noise ↔ Air Quality                              ║")
    print("╚═══════════════════════════════════════════════════════════════╝\n")

    tn_merged, ta_merged, three_way = load_and_merge()
    statistical_correlation(tn_merged, ta_merged, three_way)
    random_forest_analysis(tn_merged, ta_merged)
    lstm_results = lstm_analysis(tn_merged, ta_merged)
    write_summary(lstm_results)

    print("✓ Done!")


if __name__ == "__main__":
    main()
