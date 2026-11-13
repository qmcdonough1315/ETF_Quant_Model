"""
Joint ETF + options kill-switch (Wave C).

Fail closed: when active, options signal/order paths must skip new short premium.
See RISK_POLICY.md for allocator narrative and the 15% combined DD rule.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import config

TOTAL_BOOK_USD = float(
    getattr(config, "ETF_TARGET_CAPITAL_USD", 50_000.0)
    + getattr(config, "OPTIONS_PAPER_CAPITAL_USD", 25_000.0)
    + getattr(config, "CASH_MARGIN_RESERVE_USD", 25_000.0)
)


@dataclass(frozen=True)
class KillSwitchState:
    active: bool
    level: str  # green | yellow | red | catastrophic
    reasons: tuple[str, ...]
    combined_drawdown: Optional[float] = None
    options_pnl_usd: Optional[float] = None
    cash_reserve_usd: Optional[float] = None
    vix: Optional[float] = None

    @property
    def halt_new_short_premium(self) -> bool:
        return self.active or self.level in {"yellow", "red", "catastrophic"}


def _env_kill_forced() -> bool:
    raw = (os.environ.get("QUIRK_KILL_SWITCH") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def combined_drawdown(nav: float, peak_nav: float) -> float:
    """Drawdown as a non-negative fraction of peak (0.15 = 15%)."""
    if peak_nav is None or peak_nav <= 0 or nav is None:
        return 0.0
    return max(0.0, float(peak_nav - nav) / float(peak_nav))


def evaluate_kill_switch(
    *,
    nav: Optional[float] = None,
    peak_nav: Optional[float] = None,
    options_pnl_usd: Optional[float] = None,
    cash_reserve_usd: Optional[float] = None,
    vix: Optional[float] = None,
    force: Optional[bool] = None,
) -> KillSwitchState:
    """
    Evaluate kill-switch from measurable inputs.

    Missing inputs are ignored (not invented). Manual force / env still works.
    """
    reasons: list[str] = []
    dd = None
    if nav is not None and peak_nav is not None and peak_nav > 0:
        dd = combined_drawdown(float(nav), float(peak_nav))

    yellow_dd = float(getattr(config, "RISK_COMBINED_DD_YELLOW", 0.10))
    red_dd = float(getattr(config, "RISK_COMBINED_DD_RED", 0.15))
    cat_dd = float(getattr(config, "RISK_COMBINED_DD_CATASTROPHIC", 0.25))

    soft_opt = float(getattr(config, "RISK_OPTIONS_LOSS_SOFT_USD", -5_000.0))
    hard_opt = float(getattr(config, "RISK_OPTIONS_LOSS_HARD_USD", -10_000.0))
    reserve_floor = float(getattr(config, "RISK_CASH_RESERVE_FLOOR_USD", 12_500.0))
    vix_soft = float(getattr(config, "RISK_VIX_SOFT_HALT", 30.0))
    vix_hard = float(getattr(config, "RISK_VIX_HARD_HALT", 35.0))

    level = "green"
    active = False

    forced = _env_kill_forced() if force is None else bool(force)
    if forced:
        active = True
        level = "red"
        reasons.append("manual_or_env_kill_switch")

    if dd is not None:
        if dd >= cat_dd:
            active = True
            level = "catastrophic"
            reasons.append(f"combined_dd={dd:.1%}>=catastrophic({cat_dd:.0%})")
        elif dd >= red_dd:
            active = True
            level = "red" if level != "catastrophic" else level
            reasons.append(f"combined_dd={dd:.1%}>=red({red_dd:.0%})")
        elif dd >= yellow_dd:
            if level == "green":
                level = "yellow"
            reasons.append(f"combined_dd={dd:.1%}>=yellow({yellow_dd:.0%})")

    if options_pnl_usd is not None:
        pnl = float(options_pnl_usd)
        if pnl <= hard_opt:
            active = True
            if level not in {"catastrophic"}:
                level = "red"
            reasons.append(f"options_pnl={pnl:.0f}<=hard({hard_opt:.0f})")
        elif pnl <= soft_opt:
            if level == "green":
                level = "yellow"
            reasons.append(f"options_pnl={pnl:.0f}<=soft({soft_opt:.0f})")

    if cash_reserve_usd is not None and float(cash_reserve_usd) < reserve_floor:
        active = True
        if level not in {"catastrophic"}:
            level = "red"
        reasons.append(f"cash_reserve={float(cash_reserve_usd):.0f}<floor({reserve_floor:.0f})")

    if vix is not None:
        vx = float(vix)
        if vx >= vix_hard:
            active = True
            if level not in {"catastrophic"}:
                level = "red"
            reasons.append(f"vix={vx:.1f}>=hard({vix_hard:.0f})")
        elif vx >= vix_soft:
            if level == "green":
                level = "yellow"
            reasons.append(f"vix={vx:.1f}>=soft({vix_soft:.0f})")

    # Yellow still halts new short premium even if not fully "active" red.
    if level == "yellow" and not active:
        # Soft halt: treat as halt_new_short_premium via property; keep active False
        # so resume path can clear without a full red event — but orders must skip.
        pass

    # For order gating we treat yellow+ as skip.
    gate_active = active or level in {"yellow", "red", "catastrophic"}
    if gate_active and not reasons:
        reasons.append("kill_switch_active")

    return KillSwitchState(
        active=gate_active,
        level=level if gate_active or level != "green" else "green",
        reasons=tuple(reasons),
        combined_drawdown=dd,
        options_pnl_usd=float(options_pnl_usd) if options_pnl_usd is not None else None,
        cash_reserve_usd=float(cash_reserve_usd) if cash_reserve_usd is not None else None,
        vix=float(vix) if vix is not None else None,
    )


def kill_switch_from_env_snapshot(
    *,
    nav: Optional[float] = None,
    peak_nav: Optional[float] = None,
    options_pnl_usd: Optional[float] = None,
    cash_reserve_usd: Optional[float] = None,
    vix: Optional[float] = None,
) -> KillSwitchState:
    """
    Convenience: read optional numeric overrides from env, else use args.

    Env (presence of numbers only; never log secrets):
      QUIRK_NAV, QUIRK_PEAK_NAV, QUIRK_OPTIONS_PNL_USD,
      QUIRK_CASH_RESERVE_USD, QUIRK_VIX, QUIRK_KILL_SWITCH
    """

    def _f(name: str) -> Optional[float]:
        raw = (os.environ.get(name) or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    return evaluate_kill_switch(
        nav=_f("QUIRK_NAV") if nav is None else nav,
        peak_nav=_f("QUIRK_PEAK_NAV") if peak_nav is None else peak_nav,
        options_pnl_usd=_f("QUIRK_OPTIONS_PNL_USD") if options_pnl_usd is None else options_pnl_usd,
        cash_reserve_usd=_f("QUIRK_CASH_RESERVE_USD") if cash_reserve_usd is None else cash_reserve_usd,
        vix=_f("QUIRK_VIX") if vix is None else vix,
    )
