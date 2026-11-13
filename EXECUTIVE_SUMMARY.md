# Quirk Macro — Executive Summary

**Strategy:** Patient multi-factor ETF allocation on a **3-month investment clock**, with a **defined-risk options overlay** that monetizes elevated implied volatility while thematic positions season.

**Audience:** Allocators evaluating a research-backed, paper-trading capital stack. Detail: [`README.md`](README.md) · [`OPTIONS_BOOK.md`](OPTIONS_BOOK.md).

---

### Investment thesis

Macro and factor themes rarely reprice overnight. Empirically and in our process design, meaningful relative-value moves in liquid equity ETFs often need **about one to two quarters** to show up in prices. We do **not** claim a proprietary information advantage over the market. Our edge hypothesis is **horizon fit and patience**: size and hold exposures on a timeline matched to how long themes take to clear, rather than competing in short-horizon information races.

While those exposures mature, equity markets remain **choppy**. Option markets continuously price uncertainty. When implied volatility for select liquid ETFs sits **rich versus their own history** (high IV Rank), we can sell defined-risk premium as a second return stream. When implied volatility is **cheap**, Phase 1 **stands aside**—we refuse to sell underpriced insurance. The options book is an income and expression sleeve, not a substitute for the long-only factor portfolio.

---

### Two engines, one capital wall

| Book | Capital (paper design) | Role |
|---|---|---|
| **ETF factor selector** | $50k (13-week DCA ladder) | Long-only portfolio from ~286 ETFs; 3-month expected returns via Fama–French 5 + Carhart exposures, dynamic betas, and factor-premium forecasts; max-Sharpe sizing with name/category caps |
| **Options / vol sleeve** | $25k + $25k cash reserve | Map factor composite × IV Rank → bull put spreads, bear call spreads, or iron condors (defined risk only); never funds from the ETF sleeve |

**Benchmarking mindset:** ETF book vs patient beta (VTI / SPY / VOO DCA) on a walk-forward 3-month rebalance clock. Options book judged on process discipline, reserve usage, and risk-adjusted sleeve P&amp;L—not raw return alone.

---

### Why this can outperform—and why it might not

**Potential path to above-market results**

1. **Horizon alpha:** If 3-month factor / thematic tilts earn a premium over buy-and-hold after costs and tax frictions, patient capital wins by *not* interrupting the thesis.
2. **Volatility risk premium:** Systematically selling rich, defined-risk premium (and skipping cheap vol) has historically been a source of carry—*when* sizing and stops survive left-tail events.
3. **Complementarity:** Factor carry accrues over quarters; premium income can accrue over weeks—two clocks, one book.

**Honest constraints (allocator-grade)**

- Forecasting factor premiums is competitive and noisy; architecture ≠ proven edge until walk-forward and live results clear hurdles after fees and implementation lag.
- Short-premium overlays can lose in the same crises that hurt equities; the cash reserve and defined-risk rules mitigate, they do not eliminate, gap risk.
- Phase 1 options evaluation is **paper / process-first**; a multi-year options walk-forward comparable to the ETF research loop is still on the roadmap.
- Capacity will be limited by ETF liquidity, option markets in sector names, and tax/operational realism—not by theory.

**Bottom line for diligence:** The design is coherent and institutional in structure. **Above-market performance is a testable hypothesis, not a guarantee.** Capital should underwrite the *experiment*—documented walk-forwards, paper P&amp;L, and risk limits—not a finished track record.

---

### What capital is funding

Research-to-paper infrastructure already in repo: weekly model run, Supabase publishing, Alpaca paper execution paths, IV history bootstrap for live IV Rank (no demo vol), and tax-aware ETF DCA/TLH rules. Next diligence artifacts allocators should demand: published walk-forward tables vs VTI/SPY, options sleeve loss budget vs the $25k reserve, and a written kill-switch policy for vol regimes.
