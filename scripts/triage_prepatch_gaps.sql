-- Idempotent triage for pre-patch gap sentinel CRITICALs.
-- Resolves OPEN pipeline-completion gaps where public.price_daily already has
-- >=95% active-universe coverage. Keeps 2026-06-08..06-10 OPEN for backfill.
-- Safe to re-run: only touches rows still OPEN with pipeline-completion notes.

BEGIN;

WITH active AS (
    SELECT COUNT(*)::int AS n
      FROM theeyebeta.instruments
     WHERE active
),
threshold AS (
    SELECT (n * 0.95)::int AS min_rows
      FROM active
),
gap_coverage AS (
    SELECT g.gap_id,
           g.trade_date,
           COALESCE(
               (
                   SELECT COUNT(*)::int
                     FROM public.price_daily pd
                     JOIN theeyebeta.public_ticker_map m
                       ON m.public_ticker_id = pd.ticker_id
                    WHERE pd.date = g.trade_date
               ),
               0
           ) AS row_count,
           t.min_rows
      FROM public.audit_data_gaps g
      CROSS JOIN threshold t
     WHERE g.remediation_state = 'OPEN'
       AND g.severity IN ('CRITICAL', 'HIGH')
       AND g.remediation_notes ILIKE '%pipeline completion%'
),
to_resolve AS (
    SELECT gap_id, trade_date, row_count
      FROM gap_coverage
     WHERE row_count >= min_rows
       AND trade_date NOT IN (
           DATE '2026-06-08',
           DATE '2026-06-09',
           DATE '2026-06-10'
       )
),
updated_gaps AS (
    UPDATE public.audit_data_gaps g
       SET remediation_state = 'RESOLVED',
           remediation_notes = (
               'Pre-patch run; COMPLETED semantics introduced 2026-06-11; '
               || 'data verified present ('
               || r.row_count::text
               || ' rows)'
           ),
           updated_at = now()
      FROM to_resolve r
     WHERE g.gap_id = r.gap_id
 RETURNING g.gap_id, g.trade_date, r.row_count
)
UPDATE public.audit_alerts a
   SET resolved_at = now(),
       resolution_notes = (
           'Pre-patch triage 2026-06-11: price data verified present ('
           || ug.row_count::text
           || ' rows)'
       ),
       updated_at = now()
  FROM updated_gaps ug
 WHERE a.gap_id = ug.gap_id
   AND a.resolved_at IS NULL;

-- Show what was resolved and what remains open.
SELECT 'resolved' AS outcome, gap_id, trade_date, remediation_notes
  FROM public.audit_data_gaps
 WHERE remediation_notes ILIKE '%Pre-patch run; COMPLETED semantics introduced 2026-06-11%'
 ORDER BY trade_date;

SELECT 'still_open' AS outcome, gap_id, trade_date, severity, remediation_notes
  FROM public.audit_data_gaps
 WHERE remediation_state = 'OPEN'
   AND severity IN ('CRITICAL', 'HIGH')
   AND remediation_notes ILIKE '%pipeline completion%'
 ORDER BY trade_date;

COMMIT;
