# Options risk ops — assignment / pin / ex-div (Wave E / #11)

Phase 1 = **defined-risk short premium** on liquid ETF underlyings. American-style ETF options can be exercised early; short calls are especially exposed around **ex-dividend** dates.

Kill-switch ([`RISK_POLICY.md`](RISK_POLICY.md)) always wins: when active, **no new** short premium regardless of these rules.

---

## Rules (desk + code)

| Risk | Rule | Code / desk |
|---|---|---|
| **Ex-div (short calls)** | Do **not** open or hold short calls into a known ex-div within `OPTIONS_EX_DIV_BUFFER_DAYS` (default **7**). Applies to bear call spreads and iron condors. | `propose_defined_risk_trade(..., next_ex_div=)` skips when provided; **desk must supply / check** the date when the feed is missing |
| **Pin / gamma** | Close or roll short premium before `OPTIONS_PIN_CLOSE_DTE` (default **7** DTE). No new entries at/below that floor. | Entry also requires DTE ≥ `OPTIONS_MIN_ENTRY_DTE` (21) inside the 30–45 window |
| **Assignment** | Defined-risk wings stay on until close/roll; if short leg assigned, desk flattens the long wing same day. | Process (desk) |
| **Kill-switch** | Yellow/red / env override → skip new credit structures. | `build_signal` / propose path fail closed |

---

## Pre-trade (enforceable today)

```text
kill-switch? → skip
IVR missing or < 30? → skip
structure has short calls AND next_ex_div within buffer? → skip
DTE ≤ pin floor or < min entry? → skip
liquidity width / OI / max contracts fail? → skip
```

When `next_ex_div` is **unknown**, code cannot block — desk checklist item is mandatory before placing short-call risk (XLU, XLRE, dividend-heavy names especially).

---

## Management

- Take profit **50%** of credit; stop ~**2×** credit (unchanged).
- Into the final week (≤7 DTE): prefer **close** over hope; do not “ride pin.”
- After any assignment notice: flatten residual wing; do not invent a new naked short.

---

## Config knobs

See `config.py`: `OPTIONS_EX_DIV_BUFFER_DAYS`, `OPTIONS_PIN_CLOSE_DTE`, `OPTIONS_MIN_ENTRY_DTE`, plus liquidity table (`OPTIONS_LIQUIDITY_BY_TICKER`).
