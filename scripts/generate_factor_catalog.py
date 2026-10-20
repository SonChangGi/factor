from __future__ import annotations

from pathlib import Path

import pandas as pd

from factor_lab.advanced_factors import advanced_factor_definitions_frame
from factor_lab.factors import factor_definition_sha256, factor_definitions_frame


OUTPUT = Path("docs/factor-catalog.md")


def _cell(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, (tuple, list)):
        value = "; ".join(str(item) for item in value) or "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    frame = pd.concat(
        [factor_definitions_frame(), advanced_factor_definitions_frame()],
        ignore_index=True,
        sort=False,
    )
    frame = frame.drop_duplicates("factor").reset_index(drop=True)
    independent = int(frame["selection_eligible"].fillna(True).astype(bool).sum())
    aliases = int(frame["compatibility_alias_of"].notna().sum())
    lines = [
        "# Momentum factor catalog",
        "",
        "이 문서는 core 및 advanced factor registry에서 기계적으로 생성됩니다.",
        "",
        f"- Total factors: **{len(frame)}**",
        f"- Independent selection-eligible factors: **{independent}**",
        f"- Compatibility aliases: **{aliases}**",
        f"- Definition and implementation digest: `{factor_definition_sha256()}`",
        "- `P[t]` is adjusted close at signal date `t`; rolling windows use trading sessions.",
        "- Benchmark symbols are comparator-only and never candidate holdings.",
        "",
        "## Category coverage",
        "",
        "| Category | Count | Factor names |",
        "| --- | ---: | --- |",
    ]
    for category, group in frame.groupby("category", sort=True):
        names = ", ".join(f"`{name}`" for name in group["factor"])
        lines.append(f"| {_cell(category)} | {len(group)} | {names} |")
    lines.extend(
        [
            "",
            "## Full definitions",
            "",
            "| # | Factor | Category | Formula | Description | History | Selection | Alias | Limitations | References |",
            "| ---: | --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for index, row in frame.iterrows():
        references = (
            "; ".join(f"[{reference}]({reference})" for reference in (row.get("references") or ()))
            or "—"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index + 1),
                    f"`{_cell(row['factor'])}`",
                    _cell(row["category"]),
                    f"`{_cell(row['formula'])}`",
                    _cell(row["description"]),
                    _cell(row["minimum_history_sessions"]),
                    "independent" if bool(row["selection_eligible"]) else "excluded",
                    _cell(row["compatibility_alias_of"]),
                    _cell(row["limitations"]),
                    references,
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Shared validation contract",
            "",
            "- All factor panels preserve the input date and symbol axes.",
            "- Signal-date scores use no observations after the signal date.",
            "- Compatibility aliases remain visible but receive no independent composite score.",
            "- Missing required inputs remain missing; they are not imputed with cross-factor medians.",
            "- Actual current targets use only the final observed input row and current eligibility.",
            "",
        ]
    )
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
