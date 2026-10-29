"""Write one result-bound operational file; never modify financial files."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from factor_lab.operational_status import write_status  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, default=1)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--outcome", choices=["success", "failure", "cancelled", "skipped"], required=True
    )
    parser.add_argument("--deployment-outcome", default="skipped")
    parser.add_argument("--target")
    parser.add_argument("--started-at")
    parser.add_argument("--finished-at")
    parser.add_argument("--status-directory", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            write_status(**{key.replace("-", "_"): value for key, value in vars(args).items()})
        )
    )
