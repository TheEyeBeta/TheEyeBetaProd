-- Market data integration seed: gap row + admin market state (migration 0025).

CREATE TABLE IF NOT EXISTS public.audit_data_gaps (
    gap_id              serial PRIMARY KEY,
    dataset_type        text NOT NULL,
    trade_date          date,
    severity            text NOT NULL DEFAULT 'MEDIUM',
    remediation_state   text NOT NULL DEFAULT 'OPEN',
    remediation_notes   text,
    expected_count      int,
    actual_count        int,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.audit_data_gaps (
    gap_id, dataset_type, trade_date, severity, remediation_state, expected_count, actual_count
)
VALUES (9001, 'price_daily', CURRENT_DATE - 1, 'HIGH', 'OPEN', 500, 480)
ON CONFLICT (gap_id) DO UPDATE SET remediation_state = 'OPEN', updated_at = now();

INSERT INTO public.audit_data_gaps (
    gap_id, dataset_type, trade_date, severity, remediation_state
)
VALUES (9002, 'macro_indicators', CURRENT_DATE - 2, 'MEDIUM', 'OPEN')
ON CONFLICT (gap_id) DO UPDATE SET remediation_state = 'OPEN', updated_at = now();

INSERT INTO theeyebeta.admin_market_state (id)
VALUES (1)
ON CONFLICT DO NOTHING;
