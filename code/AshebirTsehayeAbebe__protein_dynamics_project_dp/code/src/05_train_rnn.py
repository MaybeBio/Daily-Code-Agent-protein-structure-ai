import os, sys, json, time, argparse
import numpy as np
from pathlib import Path
import tensorflow as tf

sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED

parser = argparse.ArgumentParser()
parser.add_argument("--window", type=int, default=10)
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--batch", type=int, default=64)
parser.add_argument("--epochs_tf", type=int, default=10)
parser.add_argument("--epochs_mask", type=int, default=10)
parser.add_argument("--epochs_ss", type=int, default=5)
parser.add_argument("--mask_rate", type=float, default=0.05)
parser.add_argument("--train_fraction", type=float, default=1)

args = parser.parse_args()

WINDOW = args.window
SEED = args.seed
BATCH = args.batch
EPOCHS_TF = args.epochs_tf
EPOCHS_MASK = args.epochs_mask
EPOCHS_SS = args.epochs_ss
MASK_RATE = args.mask_rate
train_fraction = float(args.train_fraction)

tf.keras.utils.set_random_seed(SEED)

WIN_DIR = PROCESSED / f"windows_w{WINDOW}_norm"
SPLITS_DIR = PROCESSED / "splits" / f"splits_w{WINDOW}"
OUT_DIR = PROCESSED / "models"
RESULTS_DIR = PROCESSED / "results_rnn"

OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

print("TensorFlow:", tf.__version__)
print("GPU available:", bool(tf.config.list_physical_devices("GPU")))

X = np.load(WIN_DIR / "X.npy", mmap_mode="r")
y = np.load(WIN_DIR / "y.npy", mmap_mode="r")

train_idx = np.load(SPLITS_DIR / "train_idx.npy")
val_idx   = np.load(SPLITS_DIR / "val_idx.npy")
test_idx  = np.load(SPLITS_DIR / "test_idx.npy")

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

X_NEXT_DIM = Dx

def make_ds(indices, shuffle=False, drop_remainder=False):
    ds = tf.data.Dataset.from_tensor_slices(indices.astype(np.int64))
    if shuffle:
        ds = ds.shuffle(min(20000, len(indices)), seed=SEED, reshuffle_each_iteration=True)
    return ds.batch(BATCH, drop_remainder=drop_remainder).prefetch(tf.data.AUTOTUNE)

train_ds = make_ds(train_idx, shuffle=True, drop_remainder=True)
val_ds   = make_ds(val_idx, shuffle=False, drop_remainder=False)
test_ds  = make_ds(test_idx, shuffle=False, drop_remainder=False)

CONFIGS = [
    {"name": "rnn_A", "units": 512, "dropout": 0.1, "lr": 3e-4},
    {"name": "rnn_B", "units": 512, "dropout": 0.2, "lr": 1e-4},
    {"name": "rnn_C", "units": 768, "dropout": 0.3, "lr": 1e-4},
]

def build_model(units, dropout):
    inp = tf.keras.Input(shape=(W, Dx), name="window")
    x = tf.keras.layers.SimpleRNN(units, name="rnn")(inp)
    if dropout > 0:
        x = tf.keras.layers.Dropout(dropout)(x)
    out = tf.keras.layers.Dense(Dy, name="pred_next")(x)
    return tf.keras.Model(inp, out, name="rnn_step07")

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
    bsz = tf.shape(xb)[0]
    mask = tf.cast(tf.random.uniform((bsz, W, Dx)) > mask_rate, xb.dtype)
    xb_mask = xb * mask
    with tf.GradientTape() as tape:
        pred = model(xb_mask, training=True)
        loss = mse(yb, pred)
    grads = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(grads, model.trainable_variables))
    return loss

def scheduled_sampling_rollout_loss(model, xb, yb, ss_prob):
    y1 = model(xb, training=True)
    loss1 = mse(yb, y1)

    x_next_pred = y1[:, :X_NEXT_DIM]
    x_next_true = yb[:, :X_NEXT_DIM]

    use_pred = tf.cast(tf.random.uniform(tf.shape(x_next_true)) < ss_prob, xb.dtype)
    x_next = use_pred * x_next_pred + (1.0 - use_pred) * x_next_true

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

def get_batch(idx_batch_np):
    xb = tf.convert_to_tensor(np.asarray(X[idx_batch_np], dtype=np.float32))
    yb = tf.convert_to_tensor(np.asarray(y[idx_batch_np], dtype=np.float32))
    return xb, yb

def run_training_one_config(cfg):
    model = build_model(cfg["units"], cfg["dropout"])
    opt = tf.keras.optimizers.Adam(learning_rate=cfg["lr"])

    dummy_x = tf.zeros((BATCH, W, Dx), dtype=tf.float32)
    _ = model(dummy_x, training=False)
    opt.build(model.trainable_variables)

    history = {"teacher": [], "masked": [], "scheduled": [], "val_mse": []}
    best_val = float("inf")
    best_path = OUT_DIR / f"{cfg['name']}_w{WINDOW}_best.keras"

    start_time = time.time()

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
        tr = float(np.mean(losses))
        va = float(np.mean(vloss))
        history["teacher"].append(tr)
        history["val_mse"].append(va)
        print(f"[TF]   Epoch {ep:02d}/{EPOCHS_TF}  train_mse={tr:.6f}  val_mse={va:.6f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

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
        tr = float(np.mean(losses))
        va = float(np.mean(vloss))
        history["masked"].append(tr)
        history["val_mse"].append(va)
        print(f"[MASK] Epoch {ep:02d}/{EPOCHS_MASK} train_mse={tr:.6f}  val_mse={va:.6f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

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
        tr = float(np.mean(losses))
        va = float(np.mean(vloss))
        history["scheduled"].append(tr)
        history["val_mse"].append(va)
        print(f"[SS]   Epoch {ep:02d}/{EPOCHS_SS}  train_loss={tr:.6f}  val_mse={va:.6f}  ss_prob={ss_prob:.2f}")
        if va < best_val:
            best_val = va
            model.save(best_path)

    best_model = tf.keras.models.load_model(best_path)
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

summary_path = RESULTS_DIR / f"RNN_step07_summary_w{WINDOW}.json"
with open(summary_path, "w") as f:
    json.dump(all_results, f, indent=2)

print("Summary saved to:", summary_path)
