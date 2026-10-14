import json

from speaker_lab_v2.scoring import score_predictions


def test_scoring_maps_anonymous_labels_without_changing_prediction_file(tmp_path):
    segments = {
        "segments": [
            {"start": 0.0, "end": 1.5},
            {"start": 1.5, "end": 2.0},
            {"start": 2.0, "end": 3.5},
            {"start": 3.5, "end": 4.0},
        ]
    }
    manual = {
        "annotations": {
            "1": "SPEAKER_00",
            "2": "SPEAKER_00",
            "3": "SPEAKER_01",
            "4": "SPEAKER_01",
        }
    }
    predictions = {
        "models": {
            "synthetic": {
                "predictions": {
                    "1": "S9",
                    "2": "S9",
                    "3": "S2",
                    "4": "S2",
                }
            }
        }
    }
    segments_path = tmp_path / "segments.json"
    manual_path = tmp_path / "labels.json"
    prediction_path = tmp_path / "predictions.json"
    segments_path.write_text(json.dumps(segments))
    manual_path.write_text(json.dumps(manual))
    prediction_path.write_text(json.dumps(predictions))
    before = prediction_path.read_bytes()

    metrics = score_predictions(prediction_path, manual_path, segments_path)

    assert metrics["models"]["synthetic"]["accuracy"] == 1.0
    assert metrics["models"]["synthetic"]["macro_f1"] == 1.0
    assert metrics["models"]["synthetic"]["long"]["count"] == 2
    assert metrics["models"]["synthetic"]["short"]["count"] == 2
    assert prediction_path.read_bytes() == before


def test_unknown_predictions_are_counted_as_errors(tmp_path):
    segments_path = tmp_path / "segments.json"
    manual_path = tmp_path / "labels.json"
    prediction_path = tmp_path / "predictions.json"
    segments_path.write_text(json.dumps({"segments": [{"start": 0.0, "end": 1.2}]}))
    manual_path.write_text(json.dumps({"annotations": {"1": "SPEAKER_00"}}))
    prediction_path.write_text(
        json.dumps({"models": {"m": {"predictions": {"1": "UNKNOWN"}}}})
    )

    metrics = score_predictions(prediction_path, manual_path, segments_path)

    assert metrics["models"]["m"]["accuracy"] == 0.0
    assert metrics["models"]["m"]["unknown_count"] == 1
