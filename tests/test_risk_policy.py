"""Wave C: combined 15% DD kill-switch and options fail-closed skip."""

from __future__ import annotations

from modules.options_sleeve import build_signal
from modules.risk_policy import combined_drawdown, evaluate_kill_switch


def test_fifteen_percent_book_dd_is_about_twenty_on_risk_sleeves():
    """50/25/25 mix: 15% NAV DD ≈ 20% on the 75% risk book if cash is flat."""
    assert abs(0.15 / 0.75 - 0.20) < 1e-12
    assert abs(combined_drawdown(85_000, 100_000) - 0.15) < 1e-12


def test_red_kill_at_fifteen_percent_combined_dd():
    state = evaluate_kill_switch(nav=85_000, peak_nav=100_000)
    assert state.active
    assert state.level == "red"
    assert state.halt_new_short_premium
    assert state.combined_drawdown == 0.15


def test_yellow_at_ten_percent_halts_new_premium():
    state = evaluate_kill_switch(nav=90_000, peak_nav=100_000)
    assert state.level == "yellow"
    assert state.halt_new_short_premium


def test_options_hard_loss_trips_kill():
    state = evaluate_kill_switch(options_pnl_usd=-10_000)
    assert state.active
    assert state.level == "red"


def test_build_signal_skips_when_kill_switch_forced():
    signal = build_signal("SPY", 1.0, 55.0, kill_switch_active=True)
    assert signal.structure == "skip_kill_switch"
    assert signal.regime == "kill_switch"


def test_build_signal_normal_when_kill_off():
    signal = build_signal("SPY", 1.0, 55.0, kill_switch_active=False)
    assert signal.structure == "bull_put_spread"
