from fastapi.testclient import TestClient

from protein_function_predictor.api import (
    create_app,
)
from protein_function_predictor.inference import (
    FunctionPrediction,
)


class FakePredictor:
    """Lightweight predictor for API tests."""

    def predict(
        self,
        sequence: str,
    ) -> list[FunctionPrediction]:
        if not sequence.strip():
            raise ValueError(
                "Protein sequence cannot be empty."
            )

        if "X" in sequence.upper():
            raise ValueError(
                "Sequence contains invalid amino acids."
            )

        return [
            FunctionPrediction(
                go_term="GO:0005524",
                probability=0.91,
                threshold=0.56,
                predicted=True,
            ),
            FunctionPrediction(
                go_term="GO:0003677",
                probability=0.12,
                threshold=0.21,
                predicted=False,
            ),
        ]


def make_client() -> TestClient:
    app = create_app(
        predictor=FakePredictor()
    )

    return TestClient(app)


def test_health_endpoint():
    with make_client() as client:
        response = client.get(
            "/health"
        )

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok"
    }


def test_predict_endpoint():
    with make_client() as client:
        response = client.post(
            "/predict",
            json={
                "sequence": "ACDEFGHIK"
            },
        )

    assert response.status_code == 200

    body = response.json()

    assert len(
        body["predictions"]
    ) == 2

    first = body[
        "predictions"
    ][0]

    assert first == {
        "go_term": "GO:0005524",
        "score": 0.91,
        "threshold": 0.56,
        "predicted": True,
    }


def test_empty_sequence_returns_422():
    with make_client() as client:
        response = client.post(
            "/predict",
            json={
                "sequence": ""
            },
        )

    assert response.status_code == 422

    assert (
        "cannot be empty"
        in response.json()["detail"]
    )


def test_invalid_sequence_returns_422():
    with make_client() as client:
        response = client.post(
            "/predict",
            json={
                "sequence": "ACDX"
            },
        )

    assert response.status_code == 422


def test_missing_sequence_returns_422():
    with make_client() as client:
        response = client.post(
            "/predict",
            json={},
        )

    assert response.status_code == 422