import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from protein_function_predictor.inference import (
    FunctionPrediction,
    ProteinFunctionPredictor,
)

DEFAULT_MODEL_PATH = Path(
    "models/baseline_logistic.joblib"
)

STATIC_DIR = (
    Path(__file__).resolve().parent
    / "static"
)


class PredictionService(Protocol):
    """Interface required by the API prediction layer."""

    def predict(
        self,
        sequence: str,
    ) -> list[FunctionPrediction]:
        ...


class PredictionRequest(BaseModel):
    """Protein sequence submitted for prediction."""

    sequence: str


class PredictionItem(BaseModel):
    """Prediction for one GO Molecular Function term."""

    go_term: str
    score: float
    threshold: float
    predicted: bool


class PredictionResponse(BaseModel):
    """API response containing GO function predictions."""

    predictions: list[PredictionItem]


class HealthResponse(BaseModel):
    """API health-check response."""

    status: str


def get_model_path() -> Path:
    """Resolve the model artifact path."""

    value = os.environ.get(
        "PFP_MODEL_PATH"
    )

    if value:
        return Path(value)

    return DEFAULT_MODEL_PATH


def create_app(
    predictor: PredictionService | None = None,
) -> FastAPI:
    """Create the protein-function prediction API."""

    @asynccontextmanager
    async def lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:
        if predictor is not None:
            app.state.predictor = predictor
        else:
            model_path = get_model_path()

            if not model_path.exists():
                raise RuntimeError(
                    "Model artifact does not exist: "
                    f"{model_path}"
                )

            app.state.predictor = (
                ProteinFunctionPredictor(
                    model_path
                )
            )

        yield

    app = FastAPI(
        title="Protein Function Predictor",
        description=(
            "Predict selected Gene Ontology "
            "Molecular Function terms from "
            "protein amino-acid sequences."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.mount(
        "/static",
        StaticFiles(
            directory=STATIC_DIR
        ),
        name="static",
    )

    @app.get(
        "/",
        include_in_schema=False,
    )
    def index() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "index.html"
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
    )
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok"
        )

    @app.post(
        "/predict",
        response_model=PredictionResponse,
    )
    def predict_sequence(
        payload: PredictionRequest,
        request: Request,
    ) -> PredictionResponse:
        prediction_service = (
            request.app.state.predictor
        )

        try:
            predictions = (
                prediction_service.predict(
                    payload.sequence
                )
            )
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail=str(error),
            ) from error

        items = [
            PredictionItem(
                go_term=prediction.go_term,
                score=prediction.probability,
                threshold=prediction.threshold,
                predicted=prediction.predicted,
            )
            for prediction in predictions
        ]

        return PredictionResponse(
            predictions=items
        )

    return app


app = create_app()