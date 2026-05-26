"""Known-good and known-bad rationale fixtures for creative classifier evaluation."""

from __future__ import annotations

# Factual / structured rationales — should score below threshold.
GOOD_RATIONALES: list[str] = [
    "technicals.AAPL.rsi14 at 55; macro.us.dgs10 at 4.25 implies range-bound conditions.",
    "prices.AAPL.close 105 with volume 1M; technicals.AAPL.atr14 1.5 supports neutral stance.",
    "macro.us.dgs10 unchanged; technicals.MSFT.rsi14 48; evidence_refs: technicals.MSFT.rsi14.",
    "HOLD: technicals.GOOGL.adx14 22 and macro.us.dgs10 4.25 show no directional edge.",
    "technicals.NVDA.rsi14 62; prices.NVDA.close above 5-day mean per packaged snapshot.",
    "Regime ranging; technicals.AMZN.bb_upper20_2 caps upside; macro.us.dgs10 stable.",
    "technicals.META.rsi14 44; prices.META.volume below 20-day average in snapshot.",
    "macro.us.dgs10 4.25; technicals.JPM.rsi14 51; decision HOLD per schema v1 output.",
    "technicals.V.rsi14 39; prices.V.adj_close flat week-over-week in snapshot JSON.",
    "technicals.UNH.rsi14 57; macro.us.dgs10 cited; horizon_days 10 per agent contract.",
    "prices.XOM.close down 2% vs snapshot as_of; technicals.XOM.atr14 elevated.",
    "technicals.CVX.rsi14 49; macro.us.dgs10 4.25; no mandate boundary triggered.",
    "technicals.PG.rsi14 53; prices.PG.close in mid Bollinger band per snapshot.",
    "macro.us.dgs10 4.25; technicals.KO.rsi14 50; key_drivers reference snapshot paths only.",
    "technicals.PEP.rsi14 46; factual read of packaged technicals.PEP block.",
    "prices.WMT.close 165; technicals.WMT.rsi14 54; neutral market_stance supported.",
    "technicals.COST.rsi14 58; macro.us.dgs10 unchanged since prior snapshot.",
    "technicals.DIS.rsi14 41; prices.DIS.low 95 from snapshot prices.DIS block.",
    "macro.us.dgs10 4.25; technicals.BA.rsi14 47; evidence_refs: macro.us.dgs10.",
    "Structured JSON decision: technicals.INTC.rsi14 36; HOLD with confidence 0.55.",
]

# Exploration / coaching language — should score at or above threshold.
BAD_RATIONALES: list[str] = [
    "I suggest increasing exposure to AAPL given momentum signals.",
    "A better approach would be to rotate into defensives before macro shifts.",
    "Have you considered reducing beta and adding hedges via index puts?",
    "In my opinion, the portfolio should exit energy names this week.",
    "Perhaps we should reconsider the HOLD and move to BUY on dips.",
    "I recommend taking profit here; a better approach is to trail stops tighter.",
    "Let me reconsider the stance — alternatively, you could add TW equities.",
    "I suggest a pairs trade: long tech vs short utilities for alpha.",
    "Have you considered that a more optimal strategy is to scale in slowly?",
    "In my opinion, macro.us.dgs10 supports a more aggressive allocation.",
    "Perhaps we should explore options overlays instead of plain equity HOLD.",
    "I recommend switching models; a better approach uses shorter horizons.",
    "I suggest you also look at small-caps for additional upside capture.",
    "Have you considered improving the signal by blending sentiment scores?",
    "Let me reconsider — alternatively, REDUCE could be upgraded to EXIT.",
    "A better approach: combine technicals.AAPL.rsi14 with discretionary overrides.",
    "I suggest raising confidence to 0.9; the evidence could be weighted differently.",
    "Perhaps we should discuss with the desk before publishing this decision.",
    "I recommend revisiting the constitution limits for this mandate.",
    "Have you considered a alternative regime label — 'transitional' fits better?",
]
