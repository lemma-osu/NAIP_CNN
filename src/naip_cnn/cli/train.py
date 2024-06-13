from __future__ import annotations

from dataclasses import dataclass

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import r2_score

import wandb
from naip_cnn import models
from naip_cnn.data import NAIPDatasetWrapper
from naip_cnn.utils.training import EpochTracker
from naip_cnn.utils.wandb import initialize_wandb_run

from . import config


@dataclass
class TrainingResult:
    model_run: models.ModelRun
    best_epoch: int
    stopped_epoch: int
    interrupted: bool = False


def load_data() -> tuple[tf.data.Dataset, tf.data.Dataset, NAIPDatasetWrapper]:
    wrapper = NAIPDatasetWrapper.from_filename(config.DATASET_NAME)

    train = (
        wrapper.load_train(
            label=config.LABEL,
            bands=config.BANDS,
            veg_indices=config.VEG_INDICES,
            augmenter=config.AUGMENT,
        )
        .cache()
        .shuffle(buffer_size=1_000)
        .batch(config.BATCH_SIZE, drop_remainder=True)
        .prefetch(tf.data.AUTOTUNE)
    )

    val = (
        wrapper.load_val(
            label=config.LABEL, bands=config.BANDS, veg_indices=config.VEG_INDICES
        )
        .cache()
        .batch(config.BATCH_SIZE, drop_remainder=True)
        .prefetch(tf.data.AUTOTUNE)
    )

    return train, val, wrapper


def load_model_run(wrapper) -> models.ModelRun:
    model = config.MODEL_CLS(
        shape=(*wrapper.naip_shape, len(config.ALL_BANDS)),
        out_shape=wrapper.lidar_shape,
        **config.MODEL_PARAMS,
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=config.LEARN_RATE),
        loss="mse",
        metrics=["mae", "mse"],
        run_eagerly=False,
    )

    return models.ModelRun(
        model=model,
        model_params=config.MODEL_PARAMS,
        dataset=wrapper,
        label=config.LABEL,
        bands=config.ALL_BANDS,
    )


def train_model(
    model_run: models.ModelRun, train: tf.data.Dataset, val: tf.data.Dataset
) -> TrainingResult:
    epoch_tracker = EpochTracker()

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            # keras does a second formatting run for the epoch
            filepath=f"./models/.checkpoint_{model_run.name}_{{epoch:04d}}.h5",
            save_best_only=True,
            save_weights_only=True,
            verbose=False,
        ),
        tf.keras.callbacks.EarlyStopping(
            verbose=1, patience=config.PATIENCE, restore_best_weights=False
        ),
        epoch_tracker,
        wandb.keras.WandbMetricsLogger(),
    ]

    try:
        model_run.model.fit(
            train,
            verbose=1,
            validation_data=val,
            epochs=config.EPOCHS,
            callbacks=callbacks,
        )
    # Allow manual early stopping
    except KeyboardInterrupt:
        model_run.model.stop_training = True
        interrupted = True
        print("\n\nTraining stopped manually. Evaluating model...\n")
    else:
        interrupted = False

    best_epoch = model_run.load_best_checkpoint()
    stopped_epoch = epoch_tracker.last_epoch

    return TrainingResult(model_run, best_epoch, stopped_epoch, interrupted)


def evaluate_model(training_result: TrainingResult, val: tf.data.Dataset) -> dict:
    y_pred = training_result.model_run.model.predict(val)
    y_true = np.concatenate([data[1] for data in val.as_numpy_iterator()])
    metric_vals = training_result.model_run.model.evaluate(val)

    metrics = {
        "best_epoch": training_result.best_epoch,
        "stopped_epoch": training_result.stopped_epoch,
        "r2_score": r2_score(y_true.ravel(), y_pred.ravel()),
    }

    for metric, value in zip(
        training_result.model_run.model.metrics_names, metric_vals
    ):
        metrics[metric] = value

    # Create evaluation figures
    log_correlation_scatterplot(y_true, y_pred)
    log_distribution_histogram(y_true, y_pred)

    # Prefix all metrics with "final/" to differentiate them from epoch metrics
    return {f"final/{k}": v for k, v in metrics.items()}


def log_distribution_histogram(y_true, y_pred):
    """Log a histogram of the true and predicted values to W&B."""
    fig, ax = plt.subplots(figsize=(6, 4))

    ax.hist(y_true.ravel(), bins=100, alpha=0.5, label="y_true")
    ax.hist(y_pred.ravel(), bins=100, alpha=0.5, label="y_pred")
    ax.legend()
    ax.set_yticks([])
    plt.tight_layout()

    wandb.log({"hist": wandb.Image(fig)})


def log_correlation_scatterplot(y_true, y_pred):
    """Log a scatterplot of the true and predicted values to W&B."""
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(y_true, y_pred, alpha=0.1, marker=".")
    ax.plot(
        (y_true.min(), y_true.max()), (y_true.min(), y_true.max()), "k-.", alpha=0.75
    )
    ax.set_xlabel("True")
    ax.set_ylabel("Predicted")
    plt.tight_layout()

    wandb.log({"scatter": wandb.Image(fig)})


def train(allow_duplicate_runs: bool, allow_cpu: bool):
    """Train a new model and log it to W&B."""
    if not allow_cpu:
        msg = "No GPU detected. Use --allow-cpu to train anyways."
        assert tf.config.list_physical_devices("GPU"), msg

    # Load the data
    train, val, wrapper = load_data()

    # Build the model
    model_run = load_model_run(wrapper)

    # Initialize the tracking experiment
    initialize_wandb_run(
        dataset=wrapper,
        model_run=model_run,
        bands=config.ALL_BANDS,
        label=config.LABEL,
        batch_size=config.BATCH_SIZE,
        learn_rate=config.LEARN_RATE,
        epochs=config.EPOCHS,
        n_train=len(train) * config.BATCH_SIZE,
        n_val=len(val) * config.BATCH_SIZE,
        augmenter=config.AUGMENT,
        allow_duplicate=allow_duplicate_runs,
    )

    # Save the repository state as an artifact
    wandb.run.log_code()

    # Train and save the model
    training_result = train_model(model_run, train, val)
    wandb.log_model(training_result.model_run.save_model())

    # Evaluate the model
    summary = evaluate_model(training_result, val)
    summary["interrupted"] = training_result.interrupted
    wandb.run.summary.update(summary)

    # Notify on run completion, unless the user ended the run manually
    if not training_result.interrupted:
        run_summary = (
            f"R^2: {summary['final/r2_score']:.4f}, MAE: {summary['final/mae']:.4f}  "
        )
        wandb.alert(title="Run Complete", text=run_summary)

    # Mark the run as complete
    wandb.run.finish()