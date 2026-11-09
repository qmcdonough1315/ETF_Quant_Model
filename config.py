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

# Paper DCA + tax-aware ledger
WEEKLY_CONTRIBUTION_USD = 1000.0
MIN_HOLD_DAYS = 91
LONG_TERM_DAYS = 365
WASH_SALE_DAYS = 30
STRATEGY_INCEPTION_DATE = "2026-09-20"

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
