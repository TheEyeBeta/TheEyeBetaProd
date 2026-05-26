/*
 * Tailwind Play CDN configuration.
 *
 * MUST be loaded BEFORE the `cdn.tailwindcss.com` script so the runtime
 * picks up dark-mode = `class` (toggled by static/js/app.js).
 */

window.tailwind = window.tailwind || {};
window.tailwind.config = {
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                severity: {
                    low: "#16a34a",
                    medium: "#ca8a04",
                    high: "#dc2626",
                    critical: "#a21caf",
                },
            },
        },
    },
};

// Apply the persisted theme *before* paint to avoid a flash of light content.
(function applyStoredTheme() {
    try {
        const saved = window.localStorage.getItem("admin-theme");
        const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        const useDark = saved === "dark" || (!saved && prefersDark);
        document.documentElement.classList.toggle("dark", useDark);
    } catch (_) {
        /* localStorage disabled (private mode) — fall back to light. */
    }
})();
