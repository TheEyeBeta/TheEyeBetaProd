# Supabase shadow report 2026-06-19

- mode: shadow
- canonical_rows: 501
- prepared_rows: 501

Live cutover requires 3 clean shadow days and operator approval.
Flip systemd ExecStart from `--shadow` to `--live`.

## Sample row

```json
{
  "ticker_id": 460,
  "ticker": "HAS",
  "company_name": "HAS",
  "last_price": 85.07,
  "last_price_ts": "2026-06-01T19:00:00+00:00",
  "price_change_pct": -8.280323,
  "price_change_abs": -7.68,
  "high_52w": 106.247479,
  "low_52w": 63.691147,
  "volume": 5135,
  "avg_volume_10d": 2201383,
  "avg_volume_30d": 2215212,
  "volume_ratio": 0.0004,
  "sma_10": 85.07,
  "sma_20": 85.619999,
  "sma_50": 85.949998,
  "sma_100": 86.046498,
  "sma_200": 86.042548,
  "ema_10": 85.217873,
  "ema_20": 85.474303,
  "ema_50": 85.802722,
  "ema_200": 85.98698,
  "rsi_14": 0.6329,
  "rsi_9": 0.0153,
  "macd": -0.302365,
  "macd_signal": -0.249537,
  "macd_histogram": -0.052828,
  "stochastic_k": 0.0,
  "stochastic_d": 0.0,
  "williams_r": -100.0,
  "cci": -66.6667,
  "adx": 53.4493,
  "bollinger_upper": 86.719997,
  "bollinger_middle": 85.619999,
  "bollinger_lower": 84.520001,
  "pe_ratio": 15.5652,
  "forward_pe": 15.5652,
  "peg_ratio": 0.0,
  "price_to_book": 33.1384,
  "price_to_sales": 0.9965,
  "dividend_yield": 2.87,
  "market_cap": 18739792631.52,
  "eps": -2.3,
  "eps_growth": 0.0,
  "revenue_growth": 0.0,
  "price_vs_sma_50": -1.0238,
  "price_vs_sma_200": -1.1303,
  "price_vs_ema_50": -0.854,
  "price_vs_ema_200": -1.0664,
  "price_vs_bollinger_middle": -0.6424,
  "is_bullish": false,
  "is_oversold": true,
  "is_overbought": false,
  "latest_signal": "BUY",
  "signal_strategy": "consensus_multi_strategy",
  "signal_confidence": 0.6039,
  "signal_timestamp": "2026-06-01T21:39:22.926061+00:00",
  "last_news_ts": null,
  "news_count_24h": null,
  "updated_at": "2026-06-01T22:39:23.029728+00:00",
  "synced_at": "2026-06-19T22:20:03.329781+00:00"
}
```
