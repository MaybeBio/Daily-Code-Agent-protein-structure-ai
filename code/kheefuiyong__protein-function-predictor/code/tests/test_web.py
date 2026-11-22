from fastapi.testclient import TestClient

from protein_function_predictor.api import (
    create_app,
)
from protein_function_predictor.inference import (
    FunctionPrediction,
)


class FakePredictor:
    def predict(
        self,
        sequence: str,
    ) -> list[FunctionPrediction]:
        return []


def make_client() -> TestClient:
    app = create_app(
        predictor=FakePredictor()
    )

    return TestClient(app)


def test_home_page_is_served():
    with make_client() as client:
        response = client.get("/")

    assert response.status_code == 200

    assert (
        "Protein Function Predictor"
        in response.text
    )


def test_stylesheet_is_served():
    with make_client() as client:
        response = client.get(
            "/static/styles.css"
        )

    assert response.status_code == 200


def test_javascript_is_served():
    with make_client() as client:
        response = client.get(
            "/static/app.js"
        )

    assert response.status_code == 200