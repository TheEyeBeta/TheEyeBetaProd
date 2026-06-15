"""
macro_series_registry.py
========================
Single source of truth for all macro series in TheEyeBeta2025Live.
Imported by every other macro script — never edit the ingestors; edit here.

Columns in each entry:
  code        : series identifier (FRED ID for auto series; custom for manual)
  name        : human-readable name
  category    : category bucket for regime analysis
  source      : data provider
  freq        : 'daily' | 'weekly' | 'monthly' | 'quarterly'
  units       : value units (informational)
  seasonal_adj: True if seasonally adjusted
  manual      : True = requires manual CSV download; False = FRED auto
  manual_url  : where to download if manual=True
  notes       : any critical notes (license restrictions, look-ahead risk, etc.)
"""

# ---------------------------------------------------------------------------
# AUTOMATED SERIES — fetched from FRED API (free, 120 req/min)
# ---------------------------------------------------------------------------

FRED_SERIES = [
    # -----------------------------------------------------------------------
    # GROWTH / ACTIVITY
    # -----------------------------------------------------------------------
    {
        "code": "GDPC1",
        "name": "Real GDP",
        "category": "growth",
        "freq": "quarterly",
        "units": "Billions Chained 2017 USD SAAR",
        "seasonal_adj": True,
        "notes": "Advance/Second/Third estimates — store all vintages",
    },
    {
        "code": "GDP",
        "name": "Nominal GDP",
        "category": "growth",
        "freq": "quarterly",
        "units": "Billions USD SAAR",
        "seasonal_adj": True,
        "notes": "",
    },
    {
        "code": "GDPDEF",
        "name": "GDP Price Deflator",
        "category": "inflation",
        "freq": "quarterly",
        "units": "Index 2017=100 SA",
        "seasonal_adj": True,
        "notes": "",
    },
    {
        "code": "INDPRO",
        "name": "Industrial Production Index",
        "category": "growth",
        "freq": "monthly",
        "units": "Index 2017=100 SA",
        "seasonal_adj": True,
        "notes": "Fed G.17 release; mid-month",
    },
    {
        "code": "TCU",
        "name": "Capacity Utilization: Total Industry",
        "category": "growth",
        "freq": "monthly",
        "units": "Percent of Capacity SA",
        "seasonal_adj": True,
        "notes": "Fed G.17",
    },
    {
        "code": "RSAFS",
        "name": "Retail Sales",
        "category": "growth",
        "freq": "monthly",
        "units": "Millions USD SA",
        "seasonal_adj": True,
        "notes": "Census advance, ~2 weeks lag",
    },
    {
        "code": "DGORDER",
        "name": "Durable Goods Orders",
        "category": "growth",
        "freq": "monthly",
        "units": "Millions USD SA",
        "seasonal_adj": True,
        "notes": "",
    },
    {
        "code": "NEWORDER",
        "name": "Core Capex Orders (Nondefense Ex-Air)",
        "category": "growth",
        "freq": "monthly",
        "units": "Millions USD SA",
        "seasonal_adj": True,
        "notes": "Proxy for business investment intentions",
    },
    {
        "code": "TOTALSA",
        "name": "Total Vehicle Sales",
        "category": "growth",
        "freq": "monthly",
        "units": "Millions of Units SAAR",
        "seasonal_adj": True,
        "notes": "",
    },
    {
        "code": "CFNAI",
        "name": "Chicago Fed National Activity Index",
        "category": "growth",
        "freq": "monthly",
        "units": "Standard Deviations",
        "seasonal_adj": True,
        "notes": "Composite of 85 economic indicators; 0=trend growth",
    },
    {
        "code": "MANEMP",
        "name": "Manufacturing Employment",
        "category": "growth",
        "freq": "monthly",
        "units": "Thousands of Persons SA",
        "seasonal_adj": True,
        "notes": "",
    },
    # -----------------------------------------------------------------------
    # INFLATION
    # -----------------------------------------------------------------------
    {
        "code": "CPIAUCSL",
        "name": "CPI All Items SA",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index 1982-84=100 SA",
        "seasonal_adj": True,
        "notes": "BLS CPI-U; ~12-14 days after reference month",
    },
    {
        "code": "CPIAUCNS",
        "name": "CPI All Items NSA",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index 1982-84=100 NSA",
        "seasonal_adj": False,
        "notes": "Use for YoY calculation to avoid seasonal distortion",
    },
    {
        "code": "CPILFESL",
        "name": "Core CPI (ex Food & Energy) SA",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index 1982-84=100 SA",
        "seasonal_adj": True,
        "notes": "Fed watches closely",
    },
    {
        "code": "PCEPI",
        "name": "PCE Price Index",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index 2017=100 SA",
        "seasonal_adj": True,
        "notes": "BEA release; lags CPI by ~2 weeks",
    },
    {
        "code": "PCEPILFE",
        "name": "Core PCE Price Index",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index 2017=100 SA",
        "seasonal_adj": True,
        "notes": "Fed's PRIMARY inflation target — most important inflation series",
    },
    {
        "code": "PPIFIS",
        "name": "PPI Final Demand",
        "category": "inflation",
        "freq": "monthly",
        "units": "Index Nov 2009=100 SA",
        "seasonal_adj": True,
        "notes": "Pipeline inflation indicator; leads CPI",
    },
    {
        "code": "CORESTICKM159SFRBATL",
        "name": "Sticky-Price CPI",
        "category": "inflation",
        "freq": "monthly",
        "units": "Percent Change from Year Ago SA",
        "seasonal_adj": True,
        "notes": "Atlanta Fed; items that change price infrequently",
    },
    {
        "code": "T5YIE",
        "name": "5-Year Breakeven Inflation Rate",
        "category": "inflation",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Market-implied; TIPS vs nominal",
    },
    {
        "code": "T10YIE",
        "name": "10-Year Breakeven Inflation Rate",
        "category": "inflation",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Most-watched inflation expectation market signal",
    },
    {
        "code": "T5YIFR",
        "name": "5-Year 5-Year Forward Inflation",
        "category": "inflation",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "ECB/Fed monitor for long-run anchoring",
    },
    {
        "code": "CES0500000003",
        "name": "Average Hourly Earnings: All Employees",
        "category": "inflation",
        "freq": "monthly",
        "units": "Dollars per Hour SA",
        "seasonal_adj": True,
        "notes": "Wage inflation — BLS CES",
    },
    {
        "code": "ECIALLCIV",
        "name": "Employment Cost Index: Civilian",
        "category": "inflation",
        "freq": "quarterly",
        "units": "Index Jun 2005=100 SA",
        "seasonal_adj": True,
        "notes": "Broader wage measure; BLS quarterly",
    },
    # -----------------------------------------------------------------------
    # LABOR MARKET
    # -----------------------------------------------------------------------
    {
        "code": "PAYEMS",
        "name": "Nonfarm Payrolls SA",
        "category": "labor",
        "freq": "monthly",
        "units": "Thousands of Persons SA",
        "seasonal_adj": True,
        "notes": "Most market-moving monthly release; HEAVILY revised — store all vintages",
    },
    {
        "code": "PAYNSA",
        "name": "Nonfarm Payrolls NSA",
        "category": "labor",
        "freq": "monthly",
        "units": "Thousands of Persons NSA",
        "seasonal_adj": False,
        "notes": "",
    },
    {
        "code": "UNRATE",
        "name": "Unemployment Rate",
        "category": "labor",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "BLS BED; headline unemployment",
    },
    {
        "code": "U6RATE",
        "name": "U-6 Underemployment Rate",
        "category": "labor",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Broadest labour slack measure",
    },
    {
        "code": "ICSA",
        "name": "Initial Jobless Claims",
        "category": "labor",
        "freq": "weekly",
        "units": "Number SA",
        "seasonal_adj": True,
        "notes": "Released Thursday; highest-freq labour signal",
    },
    {
        "code": "CCSA",
        "name": "Continued Jobless Claims",
        "category": "labor",
        "freq": "weekly",
        "units": "Number SA",
        "seasonal_adj": True,
        "notes": "Released Thursday; 1-week lag vs initial",
    },
    {
        "code": "JTSJOL",
        "name": "JOLTS Job Openings",
        "category": "labor",
        "freq": "monthly",
        "units": "Thousands SA",
        "seasonal_adj": True,
        "notes": "~6-week lag; Beveridge curve denominator",
    },
    {
        "code": "JTSQUR",
        "name": "JOLTS Quits Rate",
        "category": "labor",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Voluntary separations = worker confidence proxy",
    },
    {
        "code": "CIVPART",
        "name": "Labor Force Participation Rate",
        "category": "labor",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Structural slack measure",
    },
    {
        "code": "EMRATIO",
        "name": "Employment-Population Ratio",
        "category": "labor",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Broader than headline unemployment",
    },
    {
        "code": "ADPMNUSNERSA",
        "name": "ADP Total Nonfarm Private Payrolls (Monthly Level)",
        "category": "labor",
        "freq": "monthly",
        "units": "Thousands of Persons SA",
        "seasonal_adj": True,
        "notes": "Employment level — compute MoM change downstream. Released Wed before BLS NFP Friday.",
    },
    # -----------------------------------------------------------------------
    # CREDIT & FINANCIAL CONDITIONS
    # -----------------------------------------------------------------------
    {
        "code": "NFCI",
        "name": "Chicago Fed NFCI",
        "category": "credit",
        "freq": "weekly",
        "units": "Index (0=historical avg)",
        "seasonal_adj": False,
        "notes": "Positive = tighter than avg; composite of 105 indicators",
    },
    {
        "code": "ANFCI",
        "name": "Adjusted Chicago Fed NFCI",
        "category": "credit",
        "freq": "weekly",
        "units": "Index",
        "seasonal_adj": False,
        "notes": "Removes influence of economic conditions; purer financial conditions",
    },
    {
        "code": "BAMLC0A0CM",
        "name": "IG Corporate OAS",
        "category": "credit",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "BofA IG credit spread; key risk-off signal",
    },
    {
        "code": "BAMLH0A0HYM2",
        "name": "HY Corporate OAS",
        "category": "credit",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "BofA HY spread; stress indicator",
    },
    {
        "code": "BAMLC0A4CBBB",
        "name": "BBB Corporate OAS",
        "category": "credit",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Fallen angel risk signal",
    },
    {
        "code": "BAMLH0A0HYM2EY",
        "name": "HY Effective Yield",
        "category": "credit",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Absolute yield level of HY market",
    },
    {
        "code": "DRTSCILM",
        "name": "SLOOS: C&I Loan Standards Tightening",
        "category": "credit",
        "freq": "quarterly",
        "units": "Net Percentage",
        "seasonal_adj": False,
        "notes": "Senior Loan Officer Survey; leading credit cycle indicator",
    },
    {
        "code": "DRCCLACBS",
        "name": "Credit Card Delinquency Rate",
        "category": "credit",
        "freq": "quarterly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Consumer financial stress lagging indicator",
    },
    {
        "code": "DRSFRMACBS",
        "name": "Single-Family Mortgage Delinquency",
        "category": "credit",
        "freq": "quarterly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "Housing credit stress",
    },
    # -----------------------------------------------------------------------
    # MONETARY POLICY & RATES
    # -----------------------------------------------------------------------
    {
        "code": "EFFR",
        "name": "Fed Funds Effective Rate",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "NY Fed; actual rate vs target",
    },
    {
        "code": "DFEDTARU",
        "name": "Fed Funds Target Rate Upper Bound",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "FOMC-set ceiling",
    },
    {
        "code": "DFEDTARL",
        "name": "Fed Funds Target Rate Lower Bound",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "FOMC-set floor",
    },
    {
        "code": "SOFR",
        "name": "Secured Overnight Financing Rate",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "LIBOR replacement; NY Fed; collateralized benchmark",
    },
    {
        "code": "DGS1",
        "name": "1-Year Treasury Constant Maturity",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "H.15 release; daily",
    },
    {
        "code": "DGS2",
        "name": "2-Year Treasury Constant Maturity",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Most policy-sensitive point of curve",
    },
    {
        "code": "DGS5",
        "name": "5-Year Treasury Constant Maturity",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "",
    },
    {
        "code": "DGS10",
        "name": "10-Year Treasury Constant Maturity",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Global risk-free benchmark; most-watched rate",
    },
    {
        "code": "DGS30",
        "name": "30-Year Treasury Constant Maturity",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Long-duration; pension/mortgage benchmark",
    },
    {
        "code": "DTB3",
        "name": "3-Month T-Bill Secondary Market Rate",
        "category": "rates",
        "freq": "daily",
        "units": "Percent Discount Basis",
        "seasonal_adj": False,
        "notes": "H.15; T10Y3M spread denominator",
    },
    {
        "code": "T10Y2Y",
        "name": "10Y-2Y Treasury Spread",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Classic recession predictor; negative = inverted",
    },
    {
        "code": "T10Y3M",
        "name": "10Y-3M Treasury Spread",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "NY Fed preferred recession signal (higher predictive power in research)",
    },
    {
        "code": "WALCL",
        "name": "Fed Balance Sheet Total Assets",
        "category": "rates",
        "freq": "weekly",
        "units": "Millions USD",
        "seasonal_adj": False,
        "notes": "H.4.1; Wednesday release; QE/QT tracker",
    },
    {
        "code": "WRESBAL",
        "name": "Reserve Balances at Federal Reserve",
        "category": "rates",
        "freq": "weekly",
        "units": "Millions USD",
        "seasonal_adj": False,
        "notes": "Bank reserve abundance/scarcity",
    },
    {
        "code": "RRPONTSYD",
        "name": "Overnight Reverse Repo (ON RRP)",
        "category": "rates",
        "freq": "daily",
        "units": "Billions USD",
        "seasonal_adj": False,
        "notes": "Excess liquidity overflow valve; key plumbing signal",
    },
    {
        "code": "RPONTSYD",
        "name": "Overnight Repo Operations",
        "category": "rates",
        "freq": "daily",
        "units": "Billions USD",
        "seasonal_adj": False,
        "notes": "Fed repo facility usage",
    },
    {
        "code": "IORB",
        "name": "Interest on Reserve Balances Rate",
        "category": "rates",
        "freq": "daily",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Floor of fed funds corridor",
    },
    {
        "code": "M2SL",
        "name": "M2 Money Supply",
        "category": "rates",
        "freq": "monthly",
        "units": "Billions USD SA",
        "seasonal_adj": True,
        "notes": "H.6; broad money; monetarist inflation signal",
    },
    {
        "code": "M1SL",
        "name": "M1 Money Supply",
        "category": "rates",
        "freq": "monthly",
        "units": "Billions USD SA",
        "seasonal_adj": True,
        "notes": "Narrow money",
    },
    {
        "code": "MORTGAGE30US",
        "name": "30-Year Fixed Mortgage Rate",
        "category": "rates",
        "freq": "weekly",
        "units": "Percent",
        "seasonal_adj": False,
        "notes": "Freddie Mac PMMS; housing affordability proxy",
    },
    # -----------------------------------------------------------------------
    # HOUSING
    # -----------------------------------------------------------------------
    {
        "code": "HOUST",
        "name": "Housing Starts: Total",
        "category": "housing",
        "freq": "monthly",
        "units": "Thousands of Units SAAR",
        "seasonal_adj": True,
        "notes": "Census/HUD; construction activity; ~3 weeks lag",
    },
    {
        "code": "PERMIT",
        "name": "Building Permits: Total",
        "category": "housing",
        "freq": "monthly",
        "units": "Thousands of Units SAAR",
        "seasonal_adj": True,
        "notes": "Leading indicator; earlier than starts",
    },
    {
        "code": "HSN1F",
        "name": "New Single-Family Home Sales",
        "category": "housing",
        "freq": "monthly",
        "units": "Thousands SAAR",
        "seasonal_adj": True,
        "notes": "Census; leading to starts (contract signed = counted)",
    },
    {
        "code": "MSPUS",
        "name": "Median Sales Price: New Houses Sold",
        "category": "housing",
        "freq": "quarterly",
        "units": "Dollars",
        "seasonal_adj": False,
        "notes": "Housing price level indicator",
    },
    {
        "code": "CSUSHPINSA",
        "name": "Case-Shiller National Home Price Index",
        "category": "housing",
        "freq": "monthly",
        "units": "Index Jan 2000=100 NSA",
        "seasonal_adj": False,
        "notes": "S&P/CoreLogic; ~2-month lag; may be restricted on FRED — CHECK LICENSE before commercial use",
    },
    # -----------------------------------------------------------------------
    # TRADE & EXTERNAL
    # -----------------------------------------------------------------------
    {
        "code": "BOPGSTB",
        "name": "Trade Balance: Goods & Services",
        "category": "trade",
        "freq": "monthly",
        "units": "Millions USD SA",
        "seasonal_adj": True,
        "notes": "BEA/Census; negative = deficit",
    },
    {
        "code": "IEABC",
        "name": "Current Account Balance",
        "category": "trade",
        "freq": "quarterly",
        "units": "Millions USD SAAR",
        "seasonal_adj": True,
        "notes": "BEA; broader than trade balance",
    },
    {
        "code": "DTWEXBGS",
        "name": "Broad Trade-Weighted USD Index",
        "category": "trade",
        "freq": "daily",
        "units": "Index (Mar 1973=100)",
        "seasonal_adj": False,
        "notes": "Fed; 26-country weights; FX dollar strength proxy",
    },
    {
        "code": "DEXUSEU",
        "name": "EUR/USD Exchange Rate",
        "category": "trade",
        "freq": "daily",
        "units": "USD per EUR",
        "seasonal_adj": False,
        "notes": "Most liquid FX pair",
    },
    {
        "code": "DEXJPUS",
        "name": "USD/JPY Exchange Rate",
        "category": "trade",
        "freq": "daily",
        "units": "JPY per USD",
        "seasonal_adj": False,
        "notes": "JPY = risk-off haven currency",
    },
    {
        "code": "DEXCHUS",
        "name": "USD/CNY Exchange Rate",
        "category": "trade",
        "freq": "daily",
        "units": "CNY per USD",
        "seasonal_adj": False,
        "notes": "China FX; managed float",
    },
    {
        "code": "DEXUSUK",
        "name": "GBP/USD Exchange Rate",
        "category": "trade",
        "freq": "daily",
        "units": "USD per GBP",
        "seasonal_adj": False,
        "notes": "Cable; UK economic proxy",
    },
    # -----------------------------------------------------------------------
    # CONSUMER & SENTIMENT
    # -----------------------------------------------------------------------
    {
        "code": "UMCSENT",
        "name": "UMich Consumer Sentiment Index",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Index (1966Q1=100)",
        "seasonal_adj": False,
        "notes": "Prelim 2nd Friday, final last Friday; forward-looking spending",
    },
    {
        "code": "PI",
        "name": "Personal Income",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Billions USD SAAR",
        "seasonal_adj": True,
        "notes": "BEA; PCE Report; income side of consumer",
    },
    {
        "code": "PCE",
        "name": "Personal Consumption Expenditures",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Billions USD SAAR",
        "seasonal_adj": True,
        "notes": "BEA; spending side; ~70% of GDP",
    },
    {
        "code": "PSAVERT",
        "name": "Personal Saving Rate",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Percent SA",
        "seasonal_adj": True,
        "notes": "BEA; buffer stock measure; precautionary signal",
    },
    {
        "code": "REVOLSL",
        "name": "Revolving Consumer Credit Outstanding",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Billions USD SA",
        "seasonal_adj": True,
        "notes": "Fed G.19; primarily credit card debt",
    },
    {
        "code": "CCLACBW027SBOG",
        "name": "Credit Card Loans: All Commercial Banks",
        "category": "sentiment",
        "freq": "weekly",
        "units": "Millions USD SA",
        "seasonal_adj": True,
        "notes": "Weekly credit card balance; high-frequency consumer stress",
    },
    # -----------------------------------------------------------------------
    # LEADING INDICATORS
    # -----------------------------------------------------------------------
    {
        "code": "RECPROUSM156N",
        "name": "Smoothed US Recession Probabilities",
        "category": "leading",
        "freq": "monthly",
        "units": "Probability (0-1)",
        "seasonal_adj": False,
        "notes": "St. Louis Fed / Chauvet & Piger; Markov-switching model",
    },
    # -----------------------------------------------------------------------
    # COMMODITIES
    # -----------------------------------------------------------------------
    {
        "code": "DCOILWTICO",
        "name": "WTI Crude Oil Spot Price",
        "category": "commodities",
        "freq": "daily",
        "units": "Dollars per Barrel",
        "seasonal_adj": False,
        "notes": "Cushing Oklahoma delivery; US benchmark",
    },
    {
        "code": "DCOILBRENTEU",
        "name": "Brent Crude Oil Spot Price",
        "category": "commodities",
        "freq": "daily",
        "units": "Dollars per Barrel",
        "seasonal_adj": False,
        "notes": "North Sea; global benchmark",
    },
    {
        "code": "DHHNGSP",
        "name": "Henry Hub Natural Gas Spot Price",
        "category": "commodities",
        "freq": "daily",
        "units": "Dollars per MMBTU",
        "seasonal_adj": False,
        "notes": "US natural gas benchmark",
    },
    # GOLD — FRED discontinued LBMA fixes; ingested via yfinance GC=F (see 05_gold_ingestor.py).
    # Canonical code GOLDPMGBD228NLBM is preserved so downstream queries stay stable.
    # {"code": "GOLDPMGBD228NLBM","name": "Gold Price (COMEX GC=F)", "category": "commodities", "freq": "daily", "units": "USD per Troy Ounce", "seasonal_adj": False, "notes": "yfinance/COMEX via 05_gold_ingestor.py"},
    {
        "code": "PNRGINDEXM",
        "name": "Global Price of Energy Index",
        "category": "commodities",
        "freq": "monthly",
        "units": "Index 2016=100",
        "seasonal_adj": False,
        "notes": "IMF commodity price index",
    },
    {
        "code": "PALLFNFINDEXM",
        "name": "Global Price of All Commodities",
        "category": "commodities",
        "freq": "monthly",
        "units": "Index 2016=100",
        "seasonal_adj": False,
        "notes": "IMF; broad commodity basket",
    },
    {
        "code": "PCOPPUSDM",
        "name": "Global Price of Copper",
        "category": "commodities",
        "freq": "monthly",
        "units": "USD per Metric Ton",
        "seasonal_adj": False,
        "notes": "'Dr. Copper' — industrial demand proxy",
    },
    # -----------------------------------------------------------------------
    # CROSS-ASSET / RISK
    # -----------------------------------------------------------------------
    {
        "code": "VIXCLS",
        "name": "VIX Volatility Index",
        "category": "risk",
        "freq": "daily",
        "units": "Index",
        "seasonal_adj": False,
        "notes": "CBOE; 30-day implied vol of S&P 500; fear gauge",
    },
    {
        "code": "SP500",
        "name": "S&P 500 Index",
        "category": "risk",
        "freq": "daily",
        "units": "Index",
        "seasonal_adj": False,
        "notes": "Equity market level",
    },
    # -----------------------------------------------------------------------
    # FISCAL
    # -----------------------------------------------------------------------
    {
        "code": "MTSDS133FMS",
        "name": "Federal Surplus/Deficit (MTS)",
        "category": "fiscal",
        "freq": "monthly",
        "units": "Millions USD NSA",
        "seasonal_adj": False,
        "notes": "Treasury Monthly Treasury Statement; negative = deficit",
    },
    {
        "code": "GFDEBTN",
        "name": "Federal Debt: Total",
        "category": "fiscal",
        "freq": "quarterly",
        "units": "Millions USD",
        "seasonal_adj": False,
        "notes": "",
    },
    {
        "code": "GFDEGDQ188S",
        "name": "Federal Debt as % of GDP",
        "category": "fiscal",
        "freq": "quarterly",
        "units": "Percent of GDP SA",
        "seasonal_adj": True,
        "notes": "Solvency metric",
    },
    {
        "code": "WTREGEN",
        "name": "Treasury General Account (TGA)",
        "category": "fiscal",
        "freq": "weekly",
        "units": "Millions USD",
        "seasonal_adj": False,
        "notes": "Fed H.4.1; TGA drawdowns = liquidity injection into system",
    },
    # -----------------------------------------------------------------------
    # GLOBAL MACRO (via FRED international categories)
    # -----------------------------------------------------------------------
    {
        "code": "CP0000EZ19M086NEST",
        "name": "Euro Area CPI YoY",
        "category": "global",
        "freq": "monthly",
        "units": "Percent Change from Year Ago",
        "seasonal_adj": False,
        "notes": "Eurostat HICP via FRED",
    },
    {
        "code": "CPALTT01JPM659N",
        "name": "Japan CPI YoY",
        "category": "global",
        "freq": "monthly",
        "units": "Percent Change from Year Ago",
        "seasonal_adj": False,
        "notes": "",
    },
    {
        "code": "CPALTT01GBM659N",
        "name": "UK CPI YoY",
        "category": "global",
        "freq": "monthly",
        "units": "Percent Change from Year Ago",
        "seasonal_adj": False,
        "notes": "ONS via FRED",
    },
    {
        "code": "G7LOLITOAASTSAM",
        "name": "OECD Leading Indicator: G7",
        "category": "global",
        "freq": "monthly",
        "units": "Index",
        "seasonal_adj": True,
        "notes": "OECD CLI; 6-month forward signal",
    },
    {
        "code": "GEPUPPP",
        "name": "Global Econ Policy Uncertainty Index",
        "category": "global",
        "freq": "monthly",
        "units": "Index",
        "seasonal_adj": False,
        "notes": "Baker-Bloom-Davis; policy risk proxy",
    },
]

# ---------------------------------------------------------------------------
# MANUAL SERIES — Boss downloads these files and runs 03_manual_file_ingestor.py
# FRED cannot provide these freely for commercial use (licensed copyrighted data)
# ---------------------------------------------------------------------------

MANUAL_SERIES = [
    {
        "code": "ISM_MFG_PMI",
        "name": "ISM Manufacturing PMI",
        "category": "growth",
        "freq": "monthly",
        "units": "Index (>50=expansion)",
        "seasonal_adj": True,
        "source": "ISM",
        "manual_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/",
        "notes": "Released first business day of month. Download the historical PDF table. Non-commercial use only — confirm license for commercial redistribution.",
    },
    {
        "code": "ISM_MFG_NEW_ORDERS",
        "name": "ISM Manufacturing New Orders Index",
        "category": "growth",
        "freq": "monthly",
        "units": "Index (>50=expansion)",
        "seasonal_adj": True,
        "source": "ISM",
        "manual_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/",
        "notes": "Sub-component of ISM Mfg PMI; forward-looking orders — one of the most leading macro sub-indicators",
    },
    {
        "code": "ISM_MFG_EMPLOYMENT",
        "name": "ISM Manufacturing Employment Index",
        "category": "labor",
        "freq": "monthly",
        "units": "Index (>50=expansion)",
        "seasonal_adj": True,
        "source": "ISM",
        "manual_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/pmi/",
        "notes": "Released with manufacturing PMI",
    },
    {
        "code": "ISM_SVCS_PMI",
        "name": "ISM Services PMI",
        "category": "growth",
        "freq": "monthly",
        "units": "Index (>50=expansion)",
        "seasonal_adj": True,
        "source": "ISM",
        "manual_url": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/services/",
        "notes": "Released third business day of month; services = ~80% of US economy",
    },
    {
        "code": "CB_LEI",
        "name": "Conference Board Leading Economic Index",
        "category": "leading",
        "freq": "monthly",
        "units": "Index 2016=100",
        "seasonal_adj": True,
        "source": "Conference Board",
        "manual_url": "https://www.conference-board.org/topics/us-leading-indicators",
        "notes": "10-component composite leading indicator. Download historical data CSV from CB website after free registration. Released ~3rd week of month.",
    },
    {
        "code": "CB_CONSUMER_CONF",
        "name": "Conference Board Consumer Confidence Index",
        "category": "sentiment",
        "freq": "monthly",
        "units": "Index 1985=100",
        "seasonal_adj": True,
        "source": "Conference Board",
        "manual_url": "https://www.conference-board.org/topics/consumer-confidence",
        "notes": "Released last Tuesday of month. Separate from UMich — focuses on labor market assessment. Licensed data.",
    },
    {
        "code": "NAHB_HMI",
        "name": "NAHB Housing Market Index",
        "category": "housing",
        "freq": "monthly",
        "units": "Index (>50=positive)",
        "seasonal_adj": True,
        "source": "NAHB / Wells Fargo",
        "manual_url": "https://www.nahb.org/news-and-economics/housing-economics/indices/housing-market-index",
        "notes": "Builder sentiment; released 3rd Wednesday of month. Leading to housing starts by ~1 month. Historical data downloadable as Excel.",
    },
    {
        "code": "MOVE_INDEX",
        "name": "MOVE Index (Treasury Volatility)",
        "category": "risk",
        "freq": "daily",
        "units": "Index",
        "seasonal_adj": False,
        "source": "ICE BofA",
        "manual_url": "https://indices.theice.com/marketplace/indices/move-index",
        "notes": "Bond market VIX equivalent. ICE charges for redistribution. Check if your Massive.com or other subscription includes it. Bloomberg ticker: MOVE.",
    },
    {
        "code": "US_PMI_COMPOSITE",
        "name": "S&P Global US PMI Composite",
        "category": "growth",
        "freq": "monthly",
        "units": "Index (>50=expansion)",
        "seasonal_adj": True,
        "source": "S&P Global",
        "manual_url": "https://www.pmi.spglobal.com/",
        "notes": "Flash PMI released ~3rd week; final ~month-end. Alternative to ISM; more timely. Historical data available via S&P Global subscription or limited free press releases.",
    },
]

# ---------------------------------------------------------------------------
# COMBINED REGISTRY — use this for coverage check and reporting
# ---------------------------------------------------------------------------

ALL_FRED_CODES = [s["code"] for s in FRED_SERIES]
ALL_MANUAL_CODES = [s["code"] for s in MANUAL_SERIES]
ALL_CODES = ALL_FRED_CODES + ALL_MANUAL_CODES

SERIES_BY_CODE = {s["code"]: s for s in FRED_SERIES + MANUAL_SERIES}

# ---------------------------------------------------------------------------
# REVISION-CRITICAL SERIES — fetch ALL vintages from ALFRED for these
# These are heavily revised and must be stored bitemporally
# ---------------------------------------------------------------------------

REVISION_CRITICAL = {
    "GDPC1",
    "GDP",
    "GDPDEF",  # GDP: advance/second/third estimates
    "PAYEMS",
    "PAYNSA",  # NFP: significant annual benchmark revisions
    "PCEPI",
    "PCEPILFE",  # PCE: revised with GDP
    "CPIAUCSL",
    "CPILFESL",  # CPI: occasional methodological revisions
    "RSAFS",  # Retail sales: advance vs final
    "INDPRO",  # Industrial production: benchmark revisions
    "JTSJOL",  # JOLTS: revised monthly
}

# ---------------------------------------------------------------------------
# FREQUENCY → INGEST SCHEDULE (used by the scheduler / cron setup)
# ---------------------------------------------------------------------------

SCHEDULE_MAP = {
    "daily": "0 20 * * 1-5",  # Weekdays at 20:00 UTC (after US market close)
    "weekly": "0 21 * * 4",  # Thursdays at 21:00 UTC (claims day + H.4.1 Wednesday)
    "monthly": "0 14 8-31 * *",  # Days 8-31 of month at 14:00 UTC (after most releases)
    "quarterly": "0 14 15-31 1,4,7,10 *",  # Mid-month of quarter-end months
}

if __name__ == "__main__":
    print(f"Total FRED (automated) series: {len(FRED_SERIES)}")
    print(f"Total manual series:           {len(MANUAL_SERIES)}")
    print(f"Total series universe:         {len(ALL_CODES)}")
    print(f"Revision-critical (ALFRED):    {len(REVISION_CRITICAL)}")
    print()
    cats = {}
    for s in FRED_SERIES + MANUAL_SERIES:
        cats.setdefault(s["category"], []).append(s["code"])
    for cat, codes in sorted(cats.items()):
        print(f"  {cat:<15} {len(codes):>3} series")
