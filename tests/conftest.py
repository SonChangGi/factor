from pathlib import Path

import pytest

from factor_lab.config import RunConfig
from factor_lab.workflow import AnalysisResult, run_analysis


@pytest.fixture(scope="session")
def demo_result(tmp_path_factory: pytest.TempPathFactory) -> AnalysisResult:
    root: Path = tmp_path_factory.mktemp("demo-result")
    config = RunConfig(
        demo=True,
        demo_symbol_count=50,
        start_date="2020-01-01",
        end_date="2025-12-31",
        output_dir=root / "outputs",
        site_dir=root / "site",
    )
    return run_analysis(config)
