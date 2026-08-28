"""
Configuration Settings for Institutional Factor Model
"""

ETF_POPULATION = [
    # Core Large Cap (10)
    "VOO", "TCAF", "OAKM", "DSTL", "CGDV", "RSP", "SCHD", "AQEC", "IVV", "SPY",
    
    # Mid Cap (8)
    "IJH", "AVDE", "RNIN", "COWZ", "RDIV", "VO", "MDY", "IWR",
    
    # Small Cap (9)
    "DFAS", "AVUV", "CALF", "IJR", "VB", "DFAT", "SCHA", "VTWO", "IWM",
    
    # Growth (9)
    "VUG", "LSGR", "PCLG", "IWF", "SCHG", "AKRE", "MGK", "RPG", "IVW",
    
    # Value (9)
    "BUSA", "MFSV", "VTV", "IWD", "CGCV", "RPV", "SCHV", "IVE", "VLUE",
    
    # Momentum & High Beta (8)
    "MTUM", "PDP", "SPHB", "QMOM", "JMOM", "FDMO", "XMMO", "DWAS",
    
    # Dividend & Income Quality (8)
    "VIG", "TDVG", "DIVB", "DGRO", "SDY", "HDV", "VYM", "NOBL",
    
    # Technology (11)
    "XLK", "VGT", "FTEC", "SMH", "IGV", "SOXX", "XSD", "CLOU", "CIBR", "SKYY", "QQQ",
    
    # Health Care (8)
    "XLV", "VHT", "XBI", "IHI", "IBB", "IHF", "FHLC",
    
    # Financials (9)
    "XLF", "VFH", "KRE", "KBWB", "IAI", "KCE", "FNCL", "KBE", "IYF",
    
    # Consumer Discretionary (8)
    "XLY", "VCR", "RSPD", "XRT", "FDIS", "IYC", "CARZ", "PEJ",
    
    # Consumer Staples (8)
    "XLP", "VDC", "IYK", "FSTA", "RHS", "PBJ", "KXI", "PSL",
    
    # Energy (9)
    "XLE", "VDE", "XOP", "AMLP", "OIH", "FENY", "IYE", "FCG",
    
    # Industrials (8)
    "XLI", "VIS", "IYJ", "FIDU", "ITA", "XAR", "IYT", "JXI",
    
    # Materials & Mining (8)
    "XLB", "VAW", "XME", "FMAT", "LIT", "REMX", "SIL", "GDX",
    
    # Utilities, Infrastructure & Clean Energy (10)
    "XLU", "VPU", "IDU", "IGF", "NFRA", "PAVE", "GRID", "ICLN", "TAN", "NLR",
    
    # Real Estate (8)
    "XLRE", "VNQ", "DFAR", "IYR", "FREL", "MORT", "REZ", "INDS",
    
    # Alternatives, Commodities & Managed Futures (10)
    "DBC", "GSG", "GLD", "SLV", "DBMF", "KMLM", "CTA", "JGLO", "PDBC", "USO",
    
    # Fixed Income & Credit (10)
    "BOND", "FBND", "JCPB", "MINT", "TFLR", "AGG", "BND", "SHY", "TLT", "HYG",
    
    # International & Emerging Markets (10)
    "VEA", "IEFA", "CGIC", "DFIV", "VWO", "IEMG", "CGNG", "EMMF", "EFA", "EEM"
]

# Model Parameters
MIN_FACTOR_THRESHOLD = 0.01  
ALPHA_SHRINKAGE_WEIGHT = 0.75 # 75% weight to fund's alpha, 25% to the group mean
FORECAST_HORIZON_MONTHS = 3  # Updated from 2 to 6 months

# Overweighting Momentum (WML) and Profitability (RMW) by 50%
FACTOR_TILTS = {
    'Mkt_RF': 1.0, 
    'SMB': 1.0, 
    'HML': 1.0, 
    'RMW': 1.5, 
    'CMA': 1.0, 
    'WML': 1.5
}

# Macroeconomic Series (FRED Tickers)
MACRO_FRED_SERIES = {
    'T10Y2Y': 'yield_curve_slope',     
    'BAA10Y': 'credit_spread',         
    'CPIAUCSL': 'cpi_inflation',       
    'STLFSI4': 'financial_stress',     
    'M2SL': 'money_supply_m2',         
    'INDPRO': 'industrial_prod',       
    'DTWEXBGS': 'usd_index',           
    'DCOILWTICO': 'wti_oil',           
    'DFII10': 'real_yield_10y',
    'VIXCLS': 'vix'
}

MACRO_PCT_CHANGE_COLS = ['cpi_inflation', 'money_supply_m2', 'industrial_prod', 'usd_index', 'wti_oil']
TARGET_FACTORS = ['Mkt_RF', 'SMB', 'HML', 'RMW', 'CMA', 'WML']
