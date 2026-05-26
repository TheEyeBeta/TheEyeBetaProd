// k6 load test for the admin-service `GET /admin/orders/pending` endpoint.
//
// Default profile: 100 concurrent VUs for 60 seconds, asserts p99 < 500 ms.
//
// Required env:
//   ADMIN_BASE_URL  e.g. https://admin.theeyebeta.store  or  http://theeyebeta-mac:7200
//   ADMIN_TOKEN     bearer JWT minted via POST /admin/auth/login
//
// Optional env:
//   ADMIN_VUS=100              concurrency override
//   ADMIN_DURATION=60s         duration override
//   ADMIN_P99_BUDGET_MS=500    p99 budget override
//
// Run:
//   k6 run \
//     -e ADMIN_BASE_URL=https://admin.theeyebeta.store \
//     -e ADMIN_TOKEN="$(cat token.txt)" \
//     scripts/load_admin_orders.js
//
// Outputs JSON summary (`summary.json`) suitable for CI artifacts.

import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL = __ENV.ADMIN_BASE_URL;
const TOKEN = __ENV.ADMIN_TOKEN;
if (!BASE_URL) {
    throw new Error("ADMIN_BASE_URL is required");
}
if (!TOKEN) {
    throw new Error("ADMIN_TOKEN is required");
}

const VUS = parseInt(__ENV.ADMIN_VUS || "100", 10);
const DURATION = __ENV.ADMIN_DURATION || "60s";
const P99_BUDGET_MS = parseFloat(__ENV.ADMIN_P99_BUDGET_MS || "500");

export const options = {
    vus: VUS,
    duration: DURATION,
    thresholds: {
        // Hard SLO: p99 < 500 ms; failing this fails the run.
        http_req_duration: [`p(99)<${P99_BUDGET_MS}`],
        http_req_failed: ["rate<0.01"],
    },
    summaryTrendStats: ["min", "avg", "med", "p(95)", "p(99)", "max"],
};

const latency = new Trend("orders_pending_latency_ms", true);
const okRate = new Rate("orders_pending_ok");

export default function () {
    const res = http.get(`${BASE_URL.replace(/\/$/, "")}/admin/orders/pending`, {
        headers: {
            Authorization: `Bearer ${TOKEN}`,
            "Cache-Control": "no-store",
        },
        tags: { endpoint: "admin_orders_pending" },
    });
    latency.add(res.timings.duration);
    okRate.add(res.status === 200);
    check(res, {
        "status is 200": (r) => r.status === 200,
        "body has orders": (r) => {
            try {
                const body = r.json();
                return Array.isArray(body.orders);
            } catch (_) {
                return false;
            }
        },
    });
    // Light think time keeps VUs realistic without tanking RPS.
    sleep(0.05);
}

export function handleSummary(data) {
    return {
        "summary.json": JSON.stringify(data, null, 2),
        stdout: textSummary(data),
    };
}

// Minimal text summary so we don't depend on the chai k6 polyfill.
function textSummary(data) {
    const m = data.metrics.http_req_duration?.values || {};
    const failed = data.metrics.http_req_failed?.values?.rate ?? 0;
    return (
        `\nadmin-load summary` +
        `\n  vus=${VUS} duration=${DURATION} budget_ms=${P99_BUDGET_MS}` +
        `\n  http_req_duration: avg=${(m.avg ?? 0).toFixed(1)}ms` +
        ` p95=${(m["p(95)"] ?? 0).toFixed(1)}ms` +
        ` p99=${(m["p(99)"] ?? 0).toFixed(1)}ms` +
        ` max=${(m.max ?? 0).toFixed(1)}ms` +
        `\n  error_rate=${(failed * 100).toFixed(3)}%\n`
    );
}
