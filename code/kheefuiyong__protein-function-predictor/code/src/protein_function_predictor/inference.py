from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from protein_function_predictor.embedding import (
    ProteinEmbedder,
)


@dataclass(frozen=True)
class FunctionPrediction:
    """Prediction for one GO Molecular Function term."""

    go_term: str
    probability: float
    threshold: float
    predicted: bool


class ProteinFunctionPredictor:
    """Run protein-function inference from raw sequence."""

    def __init__(
        self,
        model_path: str | Path,
        embedder: ProteinEmbedder | None = None,
    ):
        self.model_path = Path(model_path)

        bundle = joblib.load(
            self.model_path
        )

        required_keys = {
            "classifier",
            "vocabulary",
            "thresholds",
            "embedding_model",
            "pooling",
            "embedding_dimension",
        }

        missing = (
            required_keys
            - set(bundle)
        )

        if missing:
            raise ValueError(
                "Model bundle is missing required "
                f"fields: {sorted(missing)}"
            )

        self.classifier = bundle[
            "classifier"
        ]

        self.vocabulary = list(
            bundle["vocabulary"]
        )

        self.thresholds = np.asarray(
            bundle["thresholds"],
            dtype=np.float32,
        )

        self.embedding_model = bundle[
            "embedding_model"
        ]

        self.pooling = bundle[
            "pooling"
        ]

        self.embedding_dimension = int(
            bundle["embedding_dimension"]
        )

        if len(self.vocabulary) != len(
            self.thresholds
        ):
            raise ValueError(
                "Vocabulary and threshold counts "
                "do not match."
            )

        if not np.isfinite(
            self.thresholds
        ).all():
            raise ValueError(
                "Model thresholds must be finite."
            )

        if np.any(
            (self.thresholds < 0.0)
            | (self.thresholds > 1.0)
        ):
            raise ValueError(
                "Model thresholds must lie "
                "between 0 and 1."
            )

        if self.pooling != (
            "mean_residue_pooling"
        ):
            raise ValueError(
                "Unsupported pooling strategy: "
                f"{self.pooling}"
            )

        self.embedder = (
            embedder
            if embedder is not None
            else ProteinEmbedder(
                model_checkpoint=(
                    self.embedding_model
                )
            )
        )

    def predict(
        self,
        sequence: str,
    ) -> list[FunctionPrediction]:
        """Predict GO Molecular Function terms."""

        embedding = (
            self.embedder
            .embed(sequence)
            .detach()
            .cpu()
            .numpy()
        )

        if embedding.ndim != 1:
            raise ValueError(
                "Protein embedding must be "
                "one-dimensional."
            )

        if embedding.shape[0] != (
            self.embedding_dimension
        ):
            raise ValueError(
                "Protein embedding dimension "
                "does not match the trained model."
            )

        features = embedding.reshape(
            1,
            -1,
        )

        probabilities = np.asarray(
            self.classifier.predict_proba(
                features
            )
        )[0]

        if len(probabilities) != len(
            self.vocabulary
        ):
            raise ValueError(
                "Classifier output does not match "
                "the model vocabulary."
            )

        predictions = [
            FunctionPrediction(
                go_term=label,
                probability=float(
                    probability
                ),
                threshold=float(
                    threshold
                ),
                predicted=bool(
                    probability
                    >= threshold
                ),
            )
            for (
                label,
                probability,
                threshold,
            ) in zip(
                self.vocabulary,
                probabilities,
                self.thresholds,
                strict=True,
            )
        ]

        return sorted(
            predictions,
            key=lambda prediction: (
                prediction.probability
            ),
            reverse=True,
        )