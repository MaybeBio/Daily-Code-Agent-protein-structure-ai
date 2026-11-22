import os, json, time, argparse
import numpy as np
from pathlib import Path
import sys
import tensorflow as tf
from keras.saving import register_keras_serializable

# allow importing project_root.py
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED

# -----------------------
# Args (all defaults)
# -----------------------
parser = argparse.ArgumentParser()
parser.add_argument("--window", type=int, default=10)

parser.add_argument("--epochs_tf", type=int, default=1)
parser.add_argument("--epochs_mask", type=int, default=1)
parser.add_argument("--epochs_ss", type=int, default=1)

parser.add_argument("--batch", type=int, default=64)
parser.add_argument("--mask_rate", type=float, default=0.05)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--train_fraction", type=float, default=1)

args = parser.parse_args()

train_fraction = float(args.train_fraction)
WINDOW = args.window
EPOCHS_TF = args.epochs_tf
EPOCHS_MASK = args.epochs_mask
EPOCHS_SS = args.epochs_ss
BATCH = args.batch
MASK_RATE = args.mask_rate
SEED = args.seed

tf.keras.utils.set_random_seed(SEED)

# -----------------------
# Paths
# -----------------------
WIN_DIR = PROCESSED / f"windows_w{WINDOW}_norm"
SPLITS = PROCESSED / "splits" / f"splits_w{WINDOW}"

OUT_DIR = PROCESSED / "models"
OUT_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_DIR = PROCESSED / "results_transformer"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------
# Load data
# -----------------------
print("TensorFlow:", tf.__version__)
print("GPU available:", bool(tf.config.list_physical_devices("GPU")))

X = np.load(WIN_DIR / "X.npy", mmap_mode="r")   # (N, W, Dx)
y = np.load(WIN_DIR / "y.npy", mmap_mode="r")   # (N, Dy)

train_idx = np.load(SPLITS / "train_idx.npy")
val_idx   = np.load(SPLITS / "val_idx.npy")
test_idx  = np.load(SPLITS / "test_idx.npy")

N, W, Dx = X.shape
Dy = y.shape[1]

train_idx = train_idx[train_idx < N]
val_idx   = val_idx[val_idx < N]
test_idx  = test_idx[test_idx < N]

if train_fraction < 1.0 and train_fraction>0:
    n_keep = max(1, int(len(train_idx) * train_fraction))
    train_idx = train_idx[:n_keep]
    print(f"Using train_fraction={train_fraction:.2f} -> {len(train_idx)} training windows")
else:
    print("Using full training data (train_fraction=1.0)")

print("X shape:", X.shape)
print("y shape:", y.shape)
print("window:", W, "input_dim:", Dx, "output_dim:", Dy)
print("Splits:", len(train_idx), len(val_idx), len(test_idx))

# coords+vels dim (same as X dim)
X_NEXT_DIM = Dx

def make_ds(indices, shuffle=False, drop_remainder=False):
    ds = tf.data.Dataset.from_tensor_slices(indices)
    if shuffle:
        ds = ds.shuffle(min(20000, len(indices)), reshuffle_each_iteration=True, seed=SEED)
    ds = ds.batch(BATCH, drop_remainder=drop_remainder).prefetch(tf.data.AUTOTUNE)
    return ds

train_ds = make_ds(train_idx, shuffle=True, drop_remainder=True)
val_ds   = make_ds(val_idx,   shuffle=False, drop_remainder=False)
test_ds  = make_ds(test_idx,  shuffle=False, drop_remainder=False)

# -----------------------
# Transformer components
# -----------------------
def sinusoidal_positional_encoding(length, d_model):
    pos = np.arange(length)[:, None]
    i = np.arange(d_model)[None, :]
    angle_rates = 1.0 / np.power(10000.0, (2 * (i // 2)) / np.float32(d_model))
    angles = pos * angle_rates
    pe = np.zeros((length, d_model), dtype=np.float32)
    pe[:, 0::2] = np.sin(angles[:, 0::2])
    pe[:, 1::2] = np.cos(angles[:, 1::2])
    return tf.constant(pe[None, :, :], dtype=tf.float32)

@register_keras_serializable(package="ProteinDynamics")
class TransformerBlock(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, ff_dim, dropout, **kwargs):
        super().__init__(**kwargs)
        self.d_model = d_model
        self.num_heads = num_heads
        self.ff_dim = ff_dim
        self.dropout = dropout

        self.mha = tf.keras.layers.MultiHeadAttention(
            num_heads=num_heads,
            key_dim=max(1, d_model // num_heads)
        )
        self.ffn = tf.keras.Sequential([
            tf.keras.layers.Dense(ff_dim, activation="relu"),
            tf.keras.layers.Dense(d_model),
        ])
        self.norm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.norm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.drop1 = tf.keras.layers.Dropout(dropout)
        self.drop2 = tf.keras.layers.Dropout(dropout)

    def call(self, x, training=False):
        attn = self.mha(x, x, training=training)
        x = self.norm1(x + self.drop1(attn, training=training))
        ffn = self.ffn(x, training=training)
        x = self.norm2(x + self.drop2(ffn, training=training))
        return x

    def get_config(self):
        cfg = super().get_config()
        cfg.update({
            "d_model": self.d_model,
            "num_heads": self.num_heads,
            "ff_dim": self.ff_dim,
            "dropout": self.dropout,
        })
        return cfg

def build_transformer(d_model, num_heads, ff_dim, n_layers, dropout, lr):
    inp = tf.keras.Input(shape=(W, Dx), name="window")
    x = tf.keras.layers.Dense(d_model, name="proj_in")(inp)
    x = x + sinusoidal_positional_encoding(W, d_model)

    for i in range(n_layers):
        x = TransformerBlock(d_model, num_heads, ff_dim, dropout, name=f"block_{i+1}")(x)

    last = x[:, -1, :]
    out = tf.keras.layers.Dense(Dy, name="pred_next")(last)

    model = tf.keras.Model(inp, out, name="transformer_step08")
    opt = tf.keras.optimizers.Adam(learning_rate=lr)
    return model, opt

mse = tf.keras.losses.MeanSquaredError()

@tf.function
def train_step_teacher(model, opt, xb, yb):
    with tf.GradientTape() as tape:
        pred = model(xb, training=True)
        loss = mse(yb, pred)
    grads = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(grads, model.trainable_variables))
    return loss

@tf.function
def train_step_masked(model, opt, xb, yb, mask_rate):
    B0 = tf.shape(xb)[0]
    mask = tf.cast(tf.random.uniform((B0, W, Dx)) > mask_rate, xb.dtype)
    xb_mask = xb * mask
    with tf.GradientTape() as tape:
        pred = model(xb_mask, training=True)
        loss = mse(yb, pred)
    grads = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(grads, model.trainable_variables))
    return loss

def scheduled_sampling_rollout_loss(model, xb, yb, ss_prob):
    # step-1 prediction
    y1 = model(xb, training=True)
    loss1 = mse(yb, y1)

    # build next input (coords+vels portion)
    x_next_pred = y1[:, :X_NEXT_DIM]
    x_next_true = yb[:, :X_NEXT_DIM]

    use_pred = tf.cast(tf.random.uniform(tf.shape(x_next_true)) < ss_prob, xb.dtype)
    x_next = use_pred * x_next_pred + (1.0 - use_pred) * x_next_true

    # rollout one more step, consistency loss
    x_roll = tf.concat([xb[:, 1:, :], tf.expand_dims(x_next, axis=1)], axis=1)
    y2 = model(x_roll, training=True)
    loss2 = mse(y1, y2)

    return loss1 + 0.1 * loss2

@tf.function
def train_step_scheduled(model, opt, xb, yb, ss_prob):
    with tf.GradientTape() as tape:
        loss = scheduled_sampling_rollout_loss(model, xb, yb, ss_prob)
    grads = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(grads, model.trainable_variables))
    return loss

@tf.function
def eval_step(model, xb, yb):
    pred = model(xb, training=False)
    return mse(yb, pred)

def get_batch(idx_batch):
    xb = tf.convert_to_tensor(np.asarray(X[idx_batch], dtype=np.float32))
    yb = tf.convert_to_tensor(np.asarray(y[idx_batch], dtype=np.float32))
    return xb, yb

# -----------------------
# 3 configs
# -----------------------
CONFIGS = [
    {"name": "tr_A", "d_model": 512, "heads": 8, "ff_dim": 1536,  "layers": 3, "dropout": 0.15, "lr": 1e-4},
    {"name": "tr_B", "d_model": 512, "heads": 8, "ff_dim": 1024,  "layers": 4, "dropout": 0.1, "lr": 2e-4},
    {"name": "tr_C", "d_model": 512, "heads": 8, "ff_dim": 1536, "layers": 2, "dropout": 0.2, "lr": 1.5e-4},
]

def run_training_one_config(cfg):
    model, opt = build_transformer(
        d_model=cfg["d_model"],
        num_heads=cfg["heads"],
        ff_dim=cfg["ff_dim"],
        n_layers=cfg["layers"],
        dropout=cfg["dropout"],
        lr=cfg["lr"],
    )

    # build once before tf.function usage
    dummy_x = tf.zeros((BATCH, W, Dx), dtype=tf.float32)
    _ = model(dummy_x, training=False)
    opt.build(model.trainable_variables)

    print("\n==============================")
    print("Config:", cfg)
    model.summary()

    history = {"teacher": [], "masked": [], "scheduled": [], "val_mse": []}
    best_val = float("inf")
    best_path = OUT_DIR / f"{cfg['name']}_w{WINDOW}_best.keras"

    start_time = time.time()

    # Phase 1: Teacher forcing
    for ep in range(1, EPOCHS_TF + 1):
        losses = []
        for idx_batch in train_ds:
            xb, yb = get_batch(idx_batch.numpy())
            loss = train_step_teacher(model, opt, xb, yb)
            losses.append(float(loss.numpy()))
        vloss = []
        for idx_batch in val_ds:
            xb, yb = get_batch(idx_batch.numpy())
            vloss.append(float(eval_step(model, xb, yb).numpy()))
        tr, va = float(np.mean(losses)), float(np.mean(vloss))
        history["teacher"].append(tr)
        history["val_mse"].append(va)
        print(f"[TF]   Epoch {ep:02d}/{EPOCHS_TF}  train_mse={tr:.6f}  val_mse={va:.6f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

    # Phase 2: Masked modeling
    for ep in range(1, EPOCHS_MASK + 1):
        losses = []
        for idx_batch in train_ds:
            xb, yb = get_batch(idx_batch.numpy())
            loss = train_step_masked(model, opt, xb, yb, tf.constant(MASK_RATE, tf.float32))
            losses.append(float(loss.numpy()))
        vloss = []
        for idx_batch in val_ds:
            xb, yb = get_batch(idx_batch.numpy())
            vloss.append(float(eval_step(model, xb, yb).numpy()))
        tr, va = float(np.mean(losses)), float(np.mean(vloss))
        history["masked"].append(tr)
        history["val_mse"].append(va)
        print(f"[MASK] Epoch {ep:02d}/{EPOCHS_MASK} train_mse={tr:.6f}  val_mse={va:.6f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

    # Phase 3: Scheduled sampling
    for ep in range(1, EPOCHS_SS + 1):
        ss_prob = ep / EPOCHS_SS * 0.5
        losses = []
        for idx_batch in train_ds:
            xb, yb = get_batch(idx_batch.numpy())
            loss = train_step_scheduled(model, opt, xb, yb, tf.constant(ss_prob, tf.float32))
            losses.append(float(loss.numpy()))
        vloss = []
        for idx_batch in val_ds:
            xb, yb = get_batch(idx_batch.numpy())
            vloss.append(float(eval_step(model, xb, yb).numpy()))
        tr, va = float(np.mean(losses)), float(np.mean(vloss))
        history["scheduled"].append(tr)
        history["val_mse"].append(va)
        print(f"[SS]   Epoch {ep:02d}/{EPOCHS_SS}  train_loss={tr:.6f}  val_mse={va:.6f}  ss_prob={ss_prob:.2f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

    # Test best model
    best_model = tf.keras.models.load_model(
        best_path,
        custom_objects={"TransformerBlock": TransformerBlock}
    )
    tloss = []
    for idx_batch in test_ds:
        xb, yb = get_batch(idx_batch.numpy())
        tloss.append(float(eval_step(best_model, xb, yb).numpy()))
    test_mse = float(np.mean(tloss))

    elapsed = time.time() - start_time
    result = {
        "config": cfg,
        "window": WINDOW,
        "Dx": Dx,
        "Dy": Dy,
        "best_val_mse": best_val,
        "test_mse": test_mse,
        "seconds": elapsed,
        "best_model_path": str(best_path),
        "mask_rate": MASK_RATE,
        "epochs": {"teacher": EPOCHS_TF, "masked": EPOCHS_MASK, "scheduled": EPOCHS_SS},
        "batch": BATCH,
        "seed": SEED,
        "win_dir": str(WIN_DIR),
        "splits_dir": str(SPLITS),
    }

    json_path = RESULTS_DIR / f"{cfg['name']}_w{WINDOW}_result.json"
    hist_path = RESULTS_DIR / f"{cfg['name']}_w{WINDOW}_history.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2)
    with open(hist_path, "w") as f:
        json.dump(history, f, indent=2)

    print("Saved:", json_path)
    print("Saved:", hist_path)
    return result

all_results = [run_training_one_config(cfg) for cfg in CONFIGS]

summary_path = RESULTS_DIR / f"TRANSFORMER_step08_summary_w{WINDOW}.json"
with open(summary_path, "w") as f:
    json.dump(all_results, f, indent=2)

print("\n=== DONE Step08 Transformer (norm) ===")
print("Summary saved to:", summary_path)
