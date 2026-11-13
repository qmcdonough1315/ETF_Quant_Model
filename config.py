"""
Configuration Settings for Institutional Factor Model
"""

# Universe grouped by category so portfolio construction can enforce
# single-name and category concentration limits.
ETF_CATEGORIES = {
    # Core Large Cap
    "Core Large Cap": [
        "VOO", "TCAF", "OAKM", "DSTL", "CGDV", "RSP", "SCHD", "AQEC", "IVV", "SPY",
        "VTI", "QUAL", "SPHQ", "USMV", "MOAT", "DUHP",
    ],
    # Mid Cap
    "Mid Cap": [
        "IJH", "RNIN", "COWZ", "RDIV", "VO", "MDY", "IWR",
        "IJJ", "VOE", "IWS", "DON", "RFV", "XMVM",
    ],
    # Small Cap
    "Small Cap": [
        "DFAS", "AVUV", "CALF", "IJR", "VB", "DFAT", "SCHA", "VTWO", "IWM",
        "IWN", "IWO", "SLYV", "RZV", "XSHQ", "RWJ", "DFSV",
    ],
    # Growth
    "Growth": [
        "VUG", "LSGR", "PCLG", "IWF", "SCHG", "AKRE", "MGK", "RPG", "IVW",
        "IWY", "VONG", "QQQM", "ONEQ", "LRGE",
    ],
    # Value
    "Value": [
        "BUSA", "MFSV", "VTV", "IWD", "CGCV", "RPV", "SCHV", "IVE", "VLUE",
        "AVLV", "DFLV", "FNDX", "RWL", "PWV",
    ],
    # Momentum & High Beta
    "Momentum & High Beta": [
        "MTUM", "PDP", "SPHB", "QMOM", "JMOM", "FDMO", "XMMO", "DWAS",
        "SPMO", "VFMO", "FCPI",
    ],
    # Dividend & Income Quality
    "Dividend & Income Quality": [
        "VIG", "TDVG", "DIVB", "DGRO", "SDY", "HDV", "VYM", "NOBL",
        "DGRW", "DVY", "RDVY", "SCHY", "IDV", "DIVO",
    ],
    # Technology
    "Technology": [
        "XLK", "VGT", "FTEC", "SMH", "IGV", "SOXX", "XSD", "CLOU", "CIBR", "SKYY", "QQQ",
        "FDN", "AIQ", "BOTZ", "HACK", "WCLD",
    ],
    # Health Care
    "Health Care": [
        "XLV", "VHT", "XBI", "IHI", "IBB", "IHF", "FHLC",
        "IYH", "PJP", "XHS", "BBH", "PBE",
    ],
    # Financials
    "Financials": [
        "XLF", "VFH", "KRE", "KBWB", "IAI", "KCE", "FNCL", "KBE", "IYF",
        "IAK", "KIE", "FXO", "KBWP",
    ],
    # Consumer Discretionary
    "Consumer Discretionary": [
        "XLY", "VCR", "RSPD", "XRT", "FDIS", "IYC", "CARZ", "PEJ",
        "PEZ", "ONLN", "IBUY",
    ],
    # Consumer Staples
    "Consumer Staples": [
        "XLP", "VDC", "IYK", "FSTA", "RHS", "PBJ", "KXI", "PSL",
        "PSCC", "FXG",
    ],
    # Energy
    "Energy": [
        "XLE", "VDE", "XOP", "AMLP", "OIH", "FENY", "IYE", "FCG",
        "URA", "PXE", "XES", "IEO",
    ],
    # Industrials
    "Industrials": [
        "XLI", "VIS", "IYJ", "FIDU", "ITA", "XAR", "IYT",
        "EXI", "AIRR", "PKB", "SHLD",
    ],
    # Materials & Mining
    "Materials & Mining": [
        "XLB", "VAW", "XME", "FMAT", "LIT", "REMX", "SIL", "GDX",
        "PICK", "COPX", "GDXJ", "SLVP", "BATT",
    ],
    # Utilities, Infrastructure & Clean Energy
    "Utilities / Infra / Clean Energy": [
        "XLU", "VPU", "IDU", "IGF", "NFRA", "PAVE", "GRID", "ICLN", "TAN", "NLR",
        "JXI", "IFRA", "UTES", "ZAP", "CNRG", "PBW",
    ],
    # Real Estate
    "Real Estate": [
        "XLRE", "VNQ", "DFAR", "IYR", "FREL", "MORT", "REZ", "INDS",
        "SCHH", "RWR", "SRVR", "PPTY", "HOMZ",
    ],
    # Alternatives, Commodities & Managed Futures
    "Alts / Commodities / Managed Futures": [
        "DBC", "GSG", "GLD", "SLV", "DBMF", "KMLM", "CTA", "JGLO", "PDBC", "USO",
        "FTGC", "DBA", "IAUM", "WTMF", "FMF", "BCI",
    ],
    # Fixed Income & Credit
    "Fixed Income & Credit": [
        "BOND", "FBND", "JCPB", "MINT", "TFLR", "AGG", "BND", "SHY", "TLT", "HYG",
        "IEF", "IEI", "LQD", "VCIT", "TIP", "VTIP", "BIL", "SGOV", "EMB", "SJNK",
    ],
    # International & Emerging Markets
    "International & EM": [
        "VEA", "IEFA", "CGIC", "DFIV", "VWO", "IEMG", "CGNG", "EMMF", "EFA", "EEM",
        "AVDE", "VXUS", "IXUS", "IDEV", "EFV", "EFG", "SCZ", "EMXC", "DXJ", "EWJ", "HEFA",
    ],
    # Communication Services (new sleeve)
    "Communication Services": [
        "XLC", "VOX", "FCOM", "NXTG",
    ],
}

ETF_POPULATION = [ticker for tickers in ETF_CATEGORIES.values() for ticker in tickers]

ETF_CATEGORY_BY_TICKER = {
    ticker: category
    for category, tickers in ETF_CATEGORIES.items()
    for ticker in tickers
}

# Model Parameters
MIN_FACTOR_THRESHOLD = 0.01
ALPHA_SHRINKAGE_WEIGHT = 0.75  # 75% weight to fund's alpha, 25% to the group mean
FORECAST_HORIZON_MONTHS = 3  # Holding / forecast horizon in months

# Overweight high-return value/investment factors; keep a milder momentum tilt
FACTOR_TILTS = {
    "Mkt_RF": 1.0,
    "SMB": 1.0,
    "HML": 1.5,
    "RMW": 1.0,
    "CMA": 1.5,
    "WML": 1.25,
}

# Portfolio construction (MVO)
# Single-name cap keeps any one ETF from dominating. With a 12% cap the
# mathematical floor is 9 names to fully invest; there is no forced "exactly N".
MAX_ASSET_WEIGHT = 0.12
# Category cap blocks stacking many near-substitutes from one sleeve/theme.
MAX_CATEGORY_WEIGHT = 0.30
# Drop dust weights after optimization instead of padding to a fixed count.
MIN_ASSET_WEIGHT = 0.01
# Soft upper bound on names kept after the first pass (not a target).
MAX_HOLDINGS = 15
HIGH_VOL_THRESHOLD_3M = 0.20
HIGH_VOL_SHARPE_EXCEPTION = 0.35
MVO_COV_LOOKBACK_MONTHS = 36
MVO_CANDIDATE_POOL = 40
HML_CMA_TILT_INTENSITY = 1.0

# Walk-forward research defaults (see BACKTEST_PERIODS.md)
# One-way equity cost in bps charged on each dollar traded at rebalance
# (buys and sells). Canonical headline still *prints* the assumption explicitly;
# 0 bps is research-optimistic — always also report the sensitivity ladder.
BACKTEST_EQUITY_COST_BPS_ONE_WAY = 0.0
BACKTEST_EQUITY_COST_SENSITIVITY_BPS = (0.0, 5.0, 10.0)
BACKTEST_DEFAULT_PERIOD = "FULL"
# Frozen windows for Wave A research. end=None → use latest available month in data.
# tune=False means do not fit hyperparameters on that slice (HOLD_OUT).
BACKTEST_PERIODS = {
    "FULL": {
        "start": "2019-01-31",
        "end": "2025-12-31",
        "rebalance_step_months": 3,
        "tune": True,
        "label": "Headline span post most modern ETF listings",
    },
    "HOLD_OUT": {
        "start": "2024-07-31",
        "end": None,
        "rebalance_step_months": 3,
        "tune": False,
        "label": "Report card only — do not tune knobs after locking",
    },
    "COVID": {
        "start": "2020-01-31",
        "end": "2020-12-31",
        "rebalance_step_months": 3,
        "tune": True,
        "label": "Crash + rebound",
    },
    "BEAR_22": {
        "start": "2022-01-31",
        "end": "2022-12-31",
        "rebalance_step_months": 3,
        "tune": True,
        "label": "Inflation / rates bear",
    },
    "VOL_18": {
        "start": "2018-01-31",
        "end": "2018-12-31",
        "rebalance_step_months": 3,
        "tune": True,
        "label": "Late-cycle vol spike (check universe coverage)",
    },
    "BULL_23_24": {
        "start": "2023-01-31",
        "end": "2024-06-30",
        "rebalance_step_months": 3,
        "tune": True,
        "label": "Narrow leadership / calmer vol regime",
    },
    "THEME_3_6": {
        "start": "2019-01-31",
        "end": "2025-12-31",
        "rebalance_step_months": 6,
        "tune": True,
        "label": "6-month hold ablation vs 3-month clock",
    },
}

# Paper DCA + tax-aware ledger
# Ladder $50k over the ~3-month (13-week) min-hold so one vintage matures each week.
ETF_TARGET_CAPITAL_USD = 50_000.0
DCA_WEEKS = 13
WEEKLY_CONTRIBUTION_USD = ETF_TARGET_CAPITAL_USD / DCA_WEEKS  # ≈ $3,846.15
MIN_HOLD_DAYS = 91
LONG_TERM_DAYS = 365
WASH_SALE_DAYS = 30
STRATEGY_INCEPTION_DATE = "2026-09-20"
# Wave B (#6): propose TLH/HIFO equity sells by default; set True only for paper auto-place.
PAPER_AUTO_PLACE_SELLS = False
# Reconcile drift thresholds (#5)
RECONCILE_WEIGHT_DRIFT_ABS = 0.02  # 2pp vs model target weight
RECONCILE_SHARE_DRIFT_PCT = 0.05  # 5% vs paper-lot shares

# Paper options / vol sleeve (separate from the long-only ETF book)
OPTIONS_PAPER_CAPITAL_USD = 25_000.0
CASH_MARGIN_RESERVE_USD = 25_000.0
OPTIONS_IVR_MIN = 30.0
OPTIONS_IVR_PREFERRED = 50.0
OPTIONS_DTE_MIN = 30
OPTIONS_DTE_MAX = 45
OPTIONS_PROFIT_TAKE_PCT = 0.50
OPTIONS_STOP_MULTIPLE = 2.0
OPTIONS_MAX_NAME_MARGIN_PCT = 0.02  # of total $100k book
OPTIONS_MAX_SECTOR_MARGIN_PCT = 0.12  # of options+cash ($50k)
# Credit limit conservatism vs mid: Alpaca mleg negative limit = credit.
# Soften mid-credit by this fraction so we do not assume mid fills.
OPTIONS_FILL_CREDIT_FRACTION = 0.92
# When bid/ask present, estimate package credit with sell@bid / buy@ask (tighter than mid).
OPTIONS_CREDIT_CONSERVATIVE_SIDE = True
# Options sleeve research backtest (see run_options_sleeve_backtest.py)
OPTIONS_BACKTEST_HOLD_DTE = 37  # mid of 30–45 window
OPTIONS_BACKTEST_OTM_PCT_25D = 0.045
OPTIONS_BACKTEST_OTM_PCT_18D = 0.065
OPTIONS_BACKTEST_IV_LOOKBACK_DAYS = 365

# Wave C joint risk / kill-switch (see RISK_POLICY.md)
# 50% ETF / 25% options / 25% cash → 15% book DD ≈ 20% on the risk sleeves.
RISK_COMBINED_DD_YELLOW = 0.10  # halt new short premium; review
RISK_COMBINED_DD_RED = 0.15  # primary de-risk / kill-switch
RISK_COMBINED_DD_CATASTROPHIC = 0.25
RISK_OPTIONS_LOSS_SOFT_USD = -5_000.0  # -20% of $25k options sleeve
RISK_OPTIONS_LOSS_HARD_USD = -10_000.0  # -40% of $25k
RISK_CASH_RESERVE_FLOOR_USD = 12_500.0  # 50% of $25k reserve
RISK_VIX_SOFT_HALT = 30.0
RISK_VIX_HARD_HALT = 35.0
RISK_ETF_SLEEVE_REVIEW_DD = 0.15  # review only — do not fight 3M thesis
RISK_ETF_SLEEVE_TRIM_DD = 0.25

# Macroeconomic Series (FRED Tickers)
MACRO_FRED_SERIES = {
    "T10Y2Y": "yield_curve_slope",
    "BAA10Y": "credit_spread",
    "CPIAUCSL": "cpi_inflation",
    "STLFSI4": "financial_stress",
    "M2SL": "money_supply_m2",
    "INDPRO": "industrial_prod",
    "DTWEXBGS": "usd_index",
    "DCOILWTICO": "wti_oil",
    "DFII10": "real_yield_10y",
    "VIXCLS": "vix",
}

MACRO_PCT_CHANGE_COLS = [
    "cpi_inflation",
    "money_supply_m2",
    "industrial_prod",
    "usd_index",
    "wti_oil",
]
TARGET_FACTORS = ["Mkt_RF", "SMB", "HML", "RMW", "CMA", "WML"]
