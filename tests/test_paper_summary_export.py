"""paper_portfolio summary export must skip non-numeric fields."""

from __future__ import annotations


def _filter_numeric(summary: dict) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    skipped: list[str] = []
    for metric, value in summary.items():
        try:
            if isinstance(value, bool) or value is None:
                raise TypeError(metric)
            if isinstance(value, (dict, list, tuple)):
                raise TypeError(metric)
            float(value)
        except (TypeError, ValueError):
            skipped.append(str(metric))
            continue
        kept.append(str(metric))
    return kept, skipped


def test_skips_fill_date_and_nested_payloads():
    kept, skipped = _filter_numeric(
        {
            "strategy_value": 1.0,
            "fill_date": "2026-11-16",
            "sell_proposals": {"sells": []},
            "run_count": 2,
        }
    )
    assert kept == ["strategy_value", "run_count"]
    assert "fill_date" in skipped
    assert "sell_proposals" in skipped
