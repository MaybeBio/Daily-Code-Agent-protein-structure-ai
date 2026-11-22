const sequenceInput =
    document.querySelector("#sequence");

const sequenceLength =
    document.querySelector("#sequence-length");

const predictButton =
    document.querySelector("#predict-button");

const errorMessage =
    document.querySelector("#error-message");

const resultsSection =
    document.querySelector("#results-section");

const resultsBody =
    document.querySelector("#results-body");


function normalizedLength(sequence) {
    return sequence
        .replace(/\s/g, "")
        .length;
}


function updateSequenceLength() {
    const length = normalizedLength(
        sequenceInput.value
    );

    sequenceLength.textContent =
        `${length} / 1024 residues`;
}


function formatApiError(detail) {
    if (typeof detail === "string") {
        return detail;
    }

    if (Array.isArray(detail)) {
        return detail
            .map((item) => item.msg)
            .join("; ");
    }

    return "Prediction request failed.";
}


function renderPredictions(predictions) {
    resultsBody.replaceChildren();

    for (const prediction of predictions) {
        const row =
            document.createElement("tr");

        const goTerm =
            document.createElement("td");

        goTerm.textContent =
            prediction.go_term;

        const score =
            document.createElement("td");

        score.textContent =
            prediction.score.toFixed(3);

        const threshold =
            document.createElement("td");

        threshold.textContent =
            prediction.threshold.toFixed(3);

        const predicted =
            document.createElement("td");

        predicted.textContent =
            prediction.predicted
                ? "Predicted"
                : "Not predicted";

        predicted.className =
            prediction.predicted
                ? "predicted-yes"
                : "predicted-no";

        row.append(
            goTerm,
            score,
            threshold,
            predicted
        );

        resultsBody.append(row);
    }

    resultsSection.hidden = false;
}


async function predictSequence() {
    errorMessage.hidden = true;
    resultsSection.hidden = true;

    predictButton.disabled = true;
    predictButton.textContent =
        "Predicting...";

    try {
        const response = await fetch(
            "/predict",
            {
                method: "POST",
                headers: {
                    "Content-Type":
                        "application/json",
                },
                body: JSON.stringify({
                    sequence:
                        sequenceInput.value,
                }),
            }
        );

        const body = await response.json();

        if (!response.ok) {
            throw new Error(
                formatApiError(body.detail)
            );
        }

        renderPredictions(
            body.predictions
        );
    } catch (error) {
        errorMessage.textContent =
            error instanceof Error
                ? error.message
                : "Prediction request failed.";

        errorMessage.hidden = false;
    } finally {
        predictButton.disabled = false;
        predictButton.textContent =
            "Predict function";
    }
}


sequenceInput.addEventListener(
    "input",
    updateSequenceLength
);

predictButton.addEventListener(
    "click",
    predictSequence
);

updateSequenceLength();