import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from mpl_toolkits.mplot3d import Axes3D  # For 3D plotting

# Try to import keras (for TF compatibility)
try:
    import keras  # noqa: F401
    register_keras_serializable = keras.saving.register_keras_serializable
except Exception:
    register_keras_serializable = tf.keras.utils.register_keras_serializable

@register_keras_serializable(package="ProteinDynamics")
class TransformerBlock(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, ff_dim, dropout, **kwargs):
        super().__init__(**kwargs)
        self.d_model = int(d_model)
        self.num_heads = int(num_heads)
        self.ff_dim = int(ff_dim)
        self.dropout = float(dropout)

        self.mha = tf.keras.layers.MultiHeadAttention(
            num_heads=self.num_heads,
            key_dim=max(1, self.d_model // self.num_heads),
        )
        self.ffn = tf.keras.Sequential(
            [
                tf.keras.layers.Dense(self.ff_dim, activation="relu"),
                tf.keras.layers.Dense(self.d_model),
            ]
        )
        self.norm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.norm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.drop1 = tf.keras.layers.Dropout(self.dropout)
        self.drop2 = tf.keras.layers.Dropout(self.dropout)

    def call(self, x, training=False):
        attn = self.mha(x, x, training=training)
        x = self.norm1(x + self.drop1(attn, training=training))
        ffn = self.ffn(x, training=training)
        x = self.norm2(x + self.drop2(ffn, training=training))
        return x

    def get_config(self):
        cfg = super().get_config()
        cfg.update(
            {
                "d_model": self.d_model,
                "num_heads": self.num_heads,
                "ff_dim": self.ff_dim,
                "dropout": self.dropout,
            }
        )
        return cfg


# ============================================
# KAGGLE-SPECIFIC SETUP
# ============================================
print("Setting up for Kaggle environment...")
print(f"Current directory: {Path.cwd()}")

# Kaggle directory structure
kaggle_input_dir = Path("/kaggle/input")
kaggle_working_dir = Path("/kaggle/working")

# Try to find the processed data
PROCESSED = kaggle_working_dir / "protein_dynamics_project" / "processed"
if not PROCESSED.exists():
    PROCESSED = Path.cwd() / "processed"

print(f"Using PROCESSED directory: {PROCESSED}")
PROCESSED.mkdir(parents=True, exist_ok=True)
(PROCESSED / "reports").mkdir(parents=True, exist_ok=True)
(PROCESSED / "models").mkdir(parents=True, exist_ok=True)
# ============================================


def resolve_model_path(p: str) -> Path:
    """Resolve model path from various possible locations"""
    raw = Path(p)
    
    print(f"Looking for model: {raw}")
    
    # Check common Kaggle locations
    candidates = [
        raw if raw.is_absolute() else (Path.cwd() / raw),
        PROCESSED / "models" / raw.name,
        PROCESSED / raw,
        kaggle_input_dir / raw.name,
        kaggle_input_dir / "models" / raw.name,
        kaggle_working_dir / raw,
    ]
    
    for c in candidates:
        c = c.resolve()
        print(f"  Checking: {c}")
        if c.exists():
            print(f"✅ Found model at: {c}")
            return c
    
    raise FileNotFoundError(f"Model file not found: {p}")


def load_arrays(window: int, use_denorm: bool):
    """Load training data arrays - ALWAYS load normalized data first"""
    win_dir = PROCESSED / f"windows_w{window}_norm"
    splits_dir = PROCESSED / "splits" / f"splits_w{window}"

    print(f"Looking for data in:")
    print(f"  Windows directory: {win_dir}")
    print(f"  Splits directory: {splits_dir}")

    x_path = win_dir / "X.npy"
    y_path = win_dir / "y.npy"
    stats_path = win_dir / "norm_stats.npz"
    test_idx_path = splits_dir / "test_idx.npy"

    # Check if files exist
    for path, name in [(x_path, "X.npy"), (y_path, "y.npy"), (test_idx_path, "test_idx.npy")]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {name} in {path.parent}")
    
    if use_denorm and not stats_path.exists():
        print(f"⚠️  norm_stats.npz not found, will use normalized data only")
        stats_path = None

    print(f"✅ Loading data:")
    print(f"  X (normalized) from: {x_path}")
    print(f"  y (normalized) from: {y_path}")
    print(f"  Test indices from: {test_idx_path}")
    if stats_path and stats_path.exists():
        print(f"  Stats from: {stats_path}")
    
    # Load normalized data
    x = np.load(x_path, mmap_mode="r")
    y = np.load(y_path, mmap_mode="r")
    test_idx = np.load(test_idx_path)
    test_idx = test_idx[test_idx < x.shape[0]]

    stats = np.load(stats_path) if (use_denorm and stats_path and stats_path.exists()) else None
    
    print(f"✅ Data loaded:")
    print(f"  X shape: {x.shape} (normalized)")
    print(f"  y shape: {y.shape} (normalized)")
    print(f"  Test samples: {len(test_idx)}")
    
    return x, y, test_idx, stats


def predict_in_batches(model, x, idx, batch: int, out_dim: int) -> np.ndarray:
    """Predict in batches to manage memory"""
    pred = np.zeros((len(idx), out_dim), dtype=np.float32)
    for s in range(0, len(idx), batch):
        e = min(len(idx), s + batch)
        xb = np.asarray(x[idx[s:e]], dtype=np.float32)
        pred[s:e] = model.predict(xb, batch_size=batch, verbose=0)
        if s % (10 * batch) == 0:
            print(f"  Progress: {s}/{len(idx)} samples processed")
    print(f"✅ Prediction complete: {len(idx)} samples")
    return pred


def denorm_if_needed(arr: np.ndarray, stats):
    """Denormalize if stats are provided, otherwise return normalized values"""
    if stats is None:
        return arr
    mean = stats["y_mean"].astype(np.float32)
    std = stats["y_std"].astype(np.float32)
    return arr * std[None, :] + mean[None, :]


def mse_block(a: np.ndarray, b: np.ndarray) -> float:
    """Calculate Mean Squared Error properly"""
    if a.shape != b.shape:
        raise ValueError(f"Shapes don't match: {a.shape} vs {b.shape}")
    return float(np.mean((a - b) ** 2))


def calculate_vector_mse(y_true_norm, y_pred_norm, stats=None, use_denorm=False):
    """
    Calculate MSE treating coordinates, velocities, and forces as 3D vectors
    """
    n_atoms = 138
    n_samples = y_true_norm.shape[0]
    
    # Reshape into 3D vectors: (n_samples, n_atoms, 3) for each component
    coords_true_3d = y_true_norm[:, :414].reshape(n_samples, n_atoms, 3)
    coords_pred_3d = y_pred_norm[:, :414].reshape(n_samples, n_atoms, 3)
    
    vels_true_3d = y_true_norm[:, 414:828].reshape(n_samples, n_atoms, 3)
    vels_pred_3d = y_pred_norm[:, 414:828].reshape(n_samples, n_atoms, 3)
    
    forces_true_3d = y_true_norm[:, 828:].reshape(n_samples, n_atoms, 3)
    forces_pred_3d = y_pred_norm[:, 828:].reshape(n_samples, n_atoms, 3)
    
    # Calculate vector magnitude MSE (Euclidean norm)
    def magnitude_mse(true_3d, pred_3d):
        true_mag = np.linalg.norm(true_3d, axis=2)  # Shape: (n_samples, n_atoms)
        pred_mag = np.linalg.norm(pred_3d, axis=2)
        return mse_block(true_mag, pred_mag)
    
    # Normalized MSE
    mse_coords_mag_norm = magnitude_mse(coords_true_3d, coords_pred_3d)
    mse_vels_mag_norm = magnitude_mse(vels_true_3d, vels_pred_3d)
    mse_forces_mag_norm = magnitude_mse(forces_true_3d, forces_pred_3d)
    
    # Total normalized MSE (all components)
    mse_all_norm = mse_block(y_true_norm, y_pred_norm)
    
    print(f"\n📊 3D VECTOR MAGNITUDE MSE (NORMALIZED):")
    print(f"  Coordinates: {mse_coords_mag_norm:.6f}")
    print(f"  Velocities:  {mse_vels_mag_norm:.6f}")
    print(f"  Forces:      {mse_forces_mag_norm:.6f}")
    print(f"  Total (all components): {mse_all_norm:.6f}")
    
    # Calculate denormalized if requested
    if use_denorm and stats is not None:
        mean = stats["y_mean"].astype(np.float32)
        std = stats["y_std"].astype(np.float32)
        
        # Denormalize each component
        coords_true_denorm = coords_true_3d * std[:414].reshape(1, n_atoms, 3) + mean[:414].reshape(1, n_atoms, 3)
        coords_pred_denorm = coords_pred_3d * std[:414].reshape(1, n_atoms, 3) + mean[:414].reshape(1, n_atoms, 3)
        
        vels_true_denorm = vels_true_3d * std[414:828].reshape(1, n_atoms, 3) + mean[414:828].reshape(1, n_atoms, 3)
        vels_pred_denorm = vels_pred_3d * std[414:828].reshape(1, n_atoms, 3) + mean[414:828].reshape(1, n_atoms, 3)
        
        forces_true_denorm = forces_true_3d * std[828:].reshape(1, n_atoms, 3) + mean[828:].reshape(1, n_atoms, 3)
        forces_pred_denorm = forces_pred_3d * std[828:].reshape(1, n_atoms, 3) + mean[828:].reshape(1, n_atoms, 3)
        
        # Denormalized MSE
        mse_coords_mag_denorm = magnitude_mse(coords_true_denorm, coords_pred_denorm)
        mse_vels_mag_denorm = magnitude_mse(vels_true_denorm, vels_pred_denorm)
        mse_forces_mag_denorm = magnitude_mse(forces_true_denorm, forces_pred_denorm)
        
        # Denormalize all
        y_true_denorm = y_true_norm * std[None, :] + mean[None, :]
        y_pred_denorm = y_pred_norm * std[None, :] + mean[None, :]
        mse_all_denorm = mse_block(y_true_denorm, y_pred_denorm)
        
        print(f"\n📊 3D VECTOR MAGNITUDE MSE (DENORMALIZED):")
        print(f"  Coordinates: {mse_coords_mag_denorm:.6f}")
        print(f"  Velocities:  {mse_vels_mag_denorm:.6f}")
        print(f"  Forces:      {mse_forces_mag_denorm:.6f}")
        print(f"  Total (all components): {mse_all_denorm:.6f}")
        
        return {
            # Denormalized
            "mse_all_denorm": float(mse_all_denorm),
            "mse_coords_mag_denorm": float(mse_coords_mag_denorm),
            "mse_vels_mag_denorm": float(mse_vels_mag_denorm),
            "mse_forces_mag_denorm": float(mse_forces_mag_denorm),
            # Normalized
            "mse_all_norm": float(mse_all_norm),
            "mse_coords_mag_norm": float(mse_coords_mag_norm),
            "mse_vels_mag_norm": float(mse_vels_mag_norm),
            "mse_forces_mag_norm": float(mse_forces_mag_norm),
        }
    else:
        return {
            # Normalized
            "mse_all": float(mse_all_norm),
            "mse_coords_mag": float(mse_coords_mag_norm),
            "mse_vels_mag": float(mse_vels_mag_norm),
            "mse_forces_mag": float(mse_forces_mag_norm),
            # Aliases for backward compatibility
            "mse_all_norm": float(mse_all_norm),
            "mse_coords_mag_norm": float(mse_coords_mag_norm),
            "mse_vels_mag_norm": float(mse_vels_mag_norm),
            "mse_forces_mag_norm": float(mse_forces_mag_norm),
        }


def create_single_vector_plots(y_true_norm, y_pred_norm, out_dir, out_name, window, use_denorm):
    """
    Create ONE plot per component showing actual vs predicted 3D vectors
    Each plot shows the magnitude of the vector over time (first atom)
    """
    n_atoms = 138
    n_samples = y_true_norm.shape[0]
    
    # Reshape into 3D vectors
    coords_true_3d = y_true_norm[:, :414].reshape(n_samples, n_atoms, 3)
    coords_pred_3d = y_pred_norm[:, :414].reshape(n_samples, n_atoms, 3)
    
    vels_true_3d = y_true_norm[:, 414:828].reshape(n_samples, n_atoms, 3)
    vels_pred_3d = y_pred_norm[:, 414:828].reshape(n_samples, n_atoms, 3)
    
    forces_true_3d = y_true_norm[:, 828:].reshape(n_samples, n_atoms, 3)
    forces_pred_3d = y_pred_norm[:, 828:].reshape(n_samples, n_atoms, 3)
    
    # Calculate vector magnitudes
    coords_true_mag = np.linalg.norm(coords_true_3d, axis=2)  # Shape: (n_samples, n_atoms)
    coords_pred_mag = np.linalg.norm(coords_pred_3d, axis=2)
    
    vels_true_mag = np.linalg.norm(vels_true_3d, axis=2)
    vels_pred_mag = np.linalg.norm(vels_pred_3d, axis=2)
    
    forces_true_mag = np.linalg.norm(forces_true_3d, axis=2)
    forces_pred_mag = np.linalg.norm(forces_pred_3d, axis=2)
    
    # Limit samples for clarity
    n_plot_samples = min(200, n_samples)
    
    # 1. SINGLE PLOT WITH ALL 3 COMPONENTS
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    
    components = [
        ("Coordinates", coords_true_mag, coords_pred_mag, 'blue'),
        ("Velocities", vels_true_mag, vels_pred_mag, 'green'),
        ("Forces", forces_true_mag, forces_pred_mag, 'red')
    ]
    
    for idx, (comp_name, true_mag, pred_mag, color) in enumerate(components):
        ax = axes[idx]
        
        # Plot magnitude of first atom as a SINGLE LINE for actual and predicted
        ax.plot(true_mag[:n_plot_samples, 0], 
                color=color, linestyle='-', alpha=0.8, linewidth=2,
                label=f'Actual {comp_name} (magnitude)')
        ax.plot(pred_mag[:n_plot_samples, 0], 
                color=color, linestyle='--', alpha=0.8, linewidth=2,
                label=f'Predicted {comp_name} (magnitude)')
        
        ax.set_title(f'{comp_name} - Atom 1 Vector Magnitude (First {n_plot_samples} timesteps)', fontsize=12)
        ax.set_xlabel('Timestep')
        ax.set_ylabel('Normalized Magnitude')
        ax.legend(loc='best')
        ax.grid(True, alpha=0.3)
        
        # Calculate statistics
        r = np.corrcoef(true_mag[:n_plot_samples, 0], pred_mag[:n_plot_samples, 0])[0, 1]
        rmse = np.sqrt(np.mean((true_mag[:n_plot_samples, 0] - pred_mag[:n_plot_samples, 0]) ** 2))
        
        ax.text(0.02, 0.95, f'Correlation: {r:.4f}\nRMSE: {rmse:.4f}', 
                transform=ax.transAxes, fontsize=10,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.suptitle(f'{out_name} w={window}: 3D Vector Magnitude Comparison (NORMALIZED)\n'
                 f'Each line represents the magnitude of a 3D vector', 
                fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    magnitude_path = out_dir / f"{out_name}_w{window}_vector_magnitude_single.jpg"
    plt.savefig(magnitude_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"✅ Saved single vector magnitude plot: {magnitude_path}")
    
    # 2. 3D TRAJECTORY PLOT (First atom's coordinates in 3D space)
    if n_plot_samples >= 50:  # Only create if we have enough points
        fig_3d = plt.figure(figsize=(14, 10))
        
        # Plot actual trajectory in 3D
        ax1 = fig_3d.add_subplot(121, projection='3d')
        
        # Get first atom's coordinates
        actual_x = coords_true_3d[:n_plot_samples, 0, 0]
        actual_y = coords_true_3d[:n_plot_samples, 0, 1]
        actual_z = coords_true_3d[:n_plot_samples, 0, 2]
        
        pred_x = coords_pred_3d[:n_plot_samples, 0, 0]
        pred_y = coords_pred_3d[:n_plot_samples, 0, 1]
        pred_z = coords_pred_3d[:n_plot_samples, 0, 2]
        
        # Plot actual trajectory
        scatter1 = ax1.scatter(actual_x, actual_y, actual_z, c=range(n_plot_samples), 
                              cmap='viridis', s=20, alpha=0.7, label='Actual')
        
        # Plot predicted trajectory
        scatter2 = ax1.scatter(pred_x, pred_y, pred_z, c=range(n_plot_samples), 
                              cmap='plasma', s=20, alpha=0.7, label='Predicted')
        
        ax1.set_xlabel('X (Normalized)')
        ax1.set_ylabel('Y (Normalized)')
        ax1.set_zlabel('Z (Normalized)')
        ax1.set_title(f'3D Coordinate Trajectory - Atom 1\nFirst {n_plot_samples} timesteps')
        ax1.legend()
        
        # Add colorbar
        plt.colorbar(scatter1, ax=ax1, label='Timestep')
        
        # Plot 2D projection (XY plane)
        ax2 = fig_3d.add_subplot(122)
        
        # Plot actual vs predicted in XY plane
        ax2.scatter(actual_x, actual_y, c=range(n_plot_samples), 
                   cmap='viridis', s=20, alpha=0.7, label='Actual')
        ax2.scatter(pred_x, pred_y, c=range(n_plot_samples), 
                   cmap='plasma', s=20, alpha=0.7, label='Predicted')
        
        # Connect corresponding points
        for i in range(0, n_plot_samples, 5):  # Plot every 5th point for clarity
            ax2.plot([actual_x[i], pred_x[i]], [actual_y[i], pred_y[i]], 
                    'k-', alpha=0.3, linewidth=0.5)
        
        ax2.set_xlabel('X (Normalized)')
        ax2.set_ylabel('Y (Normalized)')
        ax2.set_title(f'XY Plane Projection\nLines connect actual→predicted')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # Add colorbar
        plt.colorbar(scatter1, ax=ax2, label='Timestep')
        
        plt.suptitle(f'{out_name} w={window}: 3D Coordinate Comparison', 
                    fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        trajectory_path = out_dir / f"{out_name}_w{window}_3d_trajectory.jpg"
        plt.savefig(trajectory_path, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"✅ Saved 3D trajectory plot: {trajectory_path}")
    else:
        trajectory_path = None
    
    # 3. SCATTER PLOT: Actual vs Predicted Magnitude
    fig_scatter, axes_scatter = plt.subplots(1, 3, figsize=(18, 5))
    
    for idx, (comp_name, true_mag, pred_mag, color) in enumerate(components):
        ax = axes_scatter[idx]
        
        # Use first atom for scatter plot
        actual_values = true_mag[:, 0]
        pred_values = pred_mag[:, 0]
        
        # Subsample for clarity
        n_points = min(500, len(actual_values))
        indices = np.random.choice(len(actual_values), n_points, replace=False)
        actual_sub = actual_values[indices]
        pred_sub = pred_values[indices]
        
        # Calculate R²
        ss_res = np.sum((actual_sub - pred_sub) ** 2)
        ss_tot = np.sum((actual_sub - np.mean(actual_sub)) ** 2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        rmse = np.sqrt(np.mean((actual_sub - pred_sub) ** 2))
        
        # Scatter plot
        ax.scatter(actual_sub, pred_sub, alpha=0.5, s=20, color=color)
        
        # Perfect prediction line
        min_val = min(actual_sub.min(), pred_sub.min())
        max_val = max(actual_sub.max(), pred_sub.max())
        ax.plot([min_val, max_val], [min_val, max_val], 
                'k--', linewidth=2, label='Perfect prediction')
        
        ax.set_xlabel(f'Actual {comp_name} Magnitude', fontsize=10)
        ax.set_ylabel(f'Predicted {comp_name} Magnitude', fontsize=10)
        ax.set_title(f'{comp_name}\nR² = {r2:.4f}, RMSE = {rmse:.4f}', fontsize=11)
        ax.legend(loc='upper left')
        ax.grid(True, alpha=0.3)
    
    plt.suptitle(f'{out_name} w={window}: Vector Magnitude Scatter Plots (Atom 1)', 
                 fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    scatter_path = out_dir / f"{out_name}_w{window}_vector_scatter_single.jpg"
    plt.savefig(scatter_path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"✅ Saved vector scatter plot: {scatter_path}")
    
    # Create summary statistics
    stats_summary = {}
    components_data = [
        ("coordinates", coords_true_mag, coords_pred_mag),
        ("velocities", vels_true_mag, vels_pred_mag),
        ("forces", forces_true_mag, forces_pred_mag)
    ]
    
    for comp_name, true_mag, pred_mag in components_data:
        # Statistics for first atom
        mag_corr = np.corrcoef(true_mag[:, 0], pred_mag[:, 0])[0, 1]
        mag_rmse = np.sqrt(np.mean((true_mag[:, 0] - pred_mag[:, 0]) ** 2))
        mag_mae = np.mean(np.abs(true_mag[:, 0] - pred_mag[:, 0]))
        
        # Also calculate average across all atoms
        all_atoms_corr = np.mean([np.corrcoef(true_mag[:, i], pred_mag[:, i])[0, 1] 
                                 for i in range(n_atoms)])
        
        stats_summary[comp_name] = {
            "atom_1": {
                "correlation": float(mag_corr),
                "rmse": float(mag_rmse),
                "mae": float(mag_mae)
            },
            "all_atoms_avg": {
                "correlation": float(all_atoms_corr)
            }
        }
    
    # Save stats summary
    stats_path = out_dir / f"{out_name}_w{window}_vector_stats_single.json"
    with open(stats_path, 'w') as f:
        json.dump(stats_summary, f, indent=2)
    print(f"✅ Saved vector statistics: {stats_path}")
    
    plots = {
        "magnitude_plot": magnitude_path,
        "scatter_plot": scatter_path,
        "stats_file": stats_path
    }
    
    if trajectory_path:
        plots["trajectory_plot"] = trajectory_path
    
    return plots, stats_summary


def create_vector_mse_chart_simple(mse_results, out_dir, out_name, window, use_denorm):
    """Create simple MSE chart for vector magnitudes"""
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Determine which values to use
    if use_denorm and "mse_coords_mag_denorm" in mse_results:
        suffix = "_denorm"
        title_suffix = "(Denormalized)"
        ylabel = "MSE (Denormalized Magnitude)"
    else:
        suffix = "_norm" if "mse_coords_mag_norm" in mse_results else ""
        title_suffix = "(Normalized)"
        ylabel = "MSE (Normalized Magnitude)"
    
    # Components
    components = ["Coordinates", "Velocities", "Forces"]
    mse_values = [
        mse_results[f"mse_coords_mag{suffix}"],
        mse_results[f"mse_vels_mag{suffix}"],
        mse_results[f"mse_forces_mag{suffix}"]
    ]
    
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    
    # Create bar chart
    bars = ax.bar(components, mse_values, color=colors, alpha=0.7)
    
    # Add value labels
    for bar, value in zip(bars, mse_values):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, height + max(mse_values)/50,
                f'{value:.4f}', ha='center', va='bottom', fontweight='bold')
    
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_xlabel('3D Vector Component', fontsize=12)
    ax.set_title(f'3D Vector Magnitude MSE\n{out_name} - Window={window} {title_suffix}', 
                 fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='y')
    
    # Add ratio information
    if len(mse_values) >= 3:
        forces_to_coords = mse_values[2] / max(mse_values[0], 1e-10)
        forces_to_vels = mse_values[2] / max(mse_values[1], 1e-10)
        
        info_text = f"Forces MSE is:\n• {forces_to_coords:.1f}× Coordinates MSE\n• {forces_to_vels:.1f}× Velocities MSE"
        ax.text(0.02, 0.98, info_text, transform=ax.transAxes, fontsize=10,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    
    plt.tight_layout()
    
    out_fig = out_dir / f"{out_name}_w{window}_vector_mse_simple_{'denorm' if use_denorm else 'norm'}.jpg"
    plt.savefig(out_fig, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"✅ Saved vector MSE chart: {out_fig}")
    
    return out_fig


# ============================================
# MAIN FUNCTION - SIMPLE VECTOR ANALYSIS
# ============================================
def evaluate_model_vectors_simple(model_path_str, window=10, out_name="eval", batch=256, use_denorm=False):
    """
    Simple evaluation showing ONE plot per component with 3D vector magnitudes
    
    Parameters:
    -----------
    model_path_str : str
        Path to the model file
    window : int
        Window size
    out_name : str
        Output file name prefix
    batch : int
        Batch size for prediction
    use_denorm : bool
        Whether to calculate denormalized MSE
    """
    
    print("="*60)
    print("SIMPLE 3D VECTOR ANALYSIS")
    print("="*60)
    print(f"📊 Showing ONE plot per component with vector magnitudes")
    print(f"📈 All plots show NORMALIZED 3D vector magnitudes")
    
    reports_dir = PROCESSED / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Reports will be saved to: {reports_dir}")

    # Load data
    print(f"\n📊 Loading NORMALIZED data for window={window}...")
    x_norm, y_norm, test_idx, stats = load_arrays(window, use_denorm)
    
    # Resolve model path
    print(f"\n🔍 Looking for model: {model_path_str}")
    model_path = resolve_model_path(model_path_str)
    
    # Load the model
    print(f"\n🤖 Loading model: {model_path}")
    model = tf.keras.models.load_model(
        model_path,
        compile=False,
        custom_objects={"TransformerBlock": TransformerBlock},
    )
    print(f"✅ Model loaded successfully")
    
    # Make predictions
    print(f"\n🔮 Making predictions...")
    pred_norm = predict_in_batches(model, x_norm, test_idx, batch=batch, out_dim=y_norm.shape[1])
    yt_norm = np.asarray(y_norm[test_idx], dtype=np.float32)
    
    print(f"✅ Predictions complete")
    
    # Calculate vector MSE
    print(f"\n📈 Calculating 3D vector magnitude MSE...")
    mse_results = calculate_vector_mse(yt_norm, pred_norm, stats, use_denorm)
    
    # Complete results dictionary
    result = {
        "window": int(window),
        "model_path": str(model_path),
        "test_size": int(len(test_idx)),
        "batch": int(batch),
        "denorm_used": bool(use_denorm),
        **mse_results
    }

    # Save results JSON
    out_json = (reports_dir / f"{out_name}_w{window}_simple_vectors.json").resolve()
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)
    print(f"💾 Saved vector results: {out_json}")

    # Create simple vector MSE chart
    print(f"\n📊 Creating vector MSE chart...")
    mse_fig_path = create_vector_mse_chart_simple(mse_results, reports_dir, out_name, window, use_denorm)
    
    # Create single vector plots (ONE plot per component)
    print(f"\n🎨 Creating single vector plots...")
    plots_dict, stats_summary = create_single_vector_plots(
        y_true_norm=yt_norm,
        y_pred_norm=pred_norm,
        out_dir=reports_dir,
        out_name=out_name,
        window=window,
        use_denorm=use_denorm
    )
    
    # Add plot paths and stats to results
    result["plots"] = {
        "mse_chart": str(mse_fig_path),
        **{k: str(v) for k, v in plots_dict.items() if v is not None}
    }
    result["vector_stats"] = stats_summary
    
    # Update JSON
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2)
    print("📝 Updated JSON with vector analysis results")

    # Print summary
    print("\n" + "="*60)
    print("✅ 3D VECTOR ANALYSIS COMPLETE")
    print("="*60)
    print(f"📋 Model: {out_name}")
    print(f"📊 Window size: {window}")
    print(f"🔢 Test samples: {len(test_idx)}")
    
    # Show key vector metrics
    suffix = "_denorm" if use_denorm and "mse_coords_mag_denorm" in mse_results else "_norm"
    
    print(f"\n📊 3D VECTOR MAGNITUDE MSE ({'DENORMALIZED' if use_denorm else 'NORMALIZED'}):")
    print(f"   Coordinates: {mse_results[f'mse_coords_mag{suffix}']:.6f}")
    print(f"   Velocities:  {mse_results[f'mse_vels_mag{suffix}']:.6f}")
    print(f"   Forces:      {mse_results[f'mse_forces_mag{suffix}']:.6f}")
    
    print(f"\n📈 VECTOR CORRELATIONS (Atom 1, Normalized):")
    for component, stats in stats_summary.items():
        print(f"   {component.capitalize():12s} - Correlation: {stats['atom_1']['correlation']:.4f}")
        print(f"                   RMSE: {stats['atom_1']['rmse']:.4f}")
        print(f"                   MAE:  {stats['atom_1']['mae']:.4f}")
    
    print("="*60)
    
    # Display output paths
    print(f"\n📁 OUTPUT FILES:")
    print(f"   JSON results:       {out_json}")
    print(f"   MSE chart:          {mse_fig_path}")
    print(f"   Magnitude plot:     {plots_dict.get('magnitude_plot', 'N/A')}")
    if 'trajectory_plot' in plots_dict:
        print(f"   3D trajectory plot: {plots_dict['trajectory_plot']}")
    print(f"   Scatter plot:       {plots_dict.get('scatter_plot', 'N/A')}")
    print(f"   Vector statistics:  {plots_dict.get('stats_file', 'N/A')}")
    print("="*60)
    
    return result


# ============================================
# HOW TO USE - SIMPLE VERSION:
# ============================================
# For simple 3D vector analysis:
#
# result = evaluate_model_vectors_simple(
#     model_path_str="my_model.keras",
#     window=20,
#     out_name="my_eval",
#     use_denorm=False  # For normalized analysis
# )
# ============================================

print("\n" + "="*60)
print("SIMPLE 3D VECTOR ANALYSIS SETUP COMPLETE")
print("="*60)
print(f"📁 PROCESSED directory: {PROCESSED}")
print(f"📁 Reports directory: {PROCESSED / 'reports'}")
print("\nReady for simple 3D vector analysis!")
print("\nUse:")
print("result = evaluate_model_vectors_simple(")
print("    model_path_str='your_model.keras',")
print("    window=25,")
print("    out_name='your_evaluation',")
print("    use_denorm=False")
print(")")
print("="*60)