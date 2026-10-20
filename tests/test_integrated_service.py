import json
import pytest
from momentum_factor_lab.integrated_service import atomic_json, normalize_settings, validate_result


def test_atomic_result_preserves_good_file_on_nonfinite_failure(tmp_path):
    path = tmp_path / "result.json"
    atomic_json(path, {"nav": 1})
    with pytest.raises(ValueError):
        atomic_json(path, {"nav": float("nan")})
    assert json.loads(path.read_text()) == {"nav": 1}


@pytest.mark.parametrize(
    "settings",
    [
        {"top_n": 0},
        {"top_n": 20.5},
        {"max_weight": float("nan")},
        {"slippage_bps": -1},
        {"execution_delay_sessions": 0},
        {"arbitrary": 1},
    ],
)
def test_reject_invalid_execution_inputs(settings):
    with pytest.raises(ValueError):
        normalize_settings(settings)


def test_incomplete_result_not_publishable():
    with pytest.raises(ValueError):
        validate_result({"selection": {}, "factors": []})
