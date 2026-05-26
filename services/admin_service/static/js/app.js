/*
 * Admin shell behaviour:
 *   1. Dark-mode toggle  (persists in localStorage; root attr `class="dark"`).
 *   2. JWT injection      (attaches `Authorization: Bearer …` to every htmx request).
 *   3. htmx redirect / auth handling (HX-Redirect, 401 -> /admin/login).
 *   4. Modal lifecycle    (ESC + backdrop close `#modal`).
 *
 * No external dependencies; loaded with `defer` so the DOM is ready.
 * Tailwind config + the pre-paint theme application live in
 * `tailwind-config.js` to avoid a flash of unstyled content.
 */

(function () {
    "use strict";

    const TOKEN_STORAGE_KEY = "admin-access-token";
    const THEME_STORAGE_KEY = "admin-theme";

    /* -------------------------------------------------------------------- */
    /*  Dark-mode toggle                                                    */
    /* -------------------------------------------------------------------- */

    function syncThemeIcons() {
        const dark = document.documentElement.classList.contains("dark");
        document
            .querySelectorAll("[data-theme-icon-light]")
            .forEach((el) => el.classList.toggle("hidden", dark));
        document
            .querySelectorAll("[data-theme-icon-dark]")
            .forEach((el) => el.classList.toggle("hidden", !dark));
    }

    function toggleTheme() {
        const root = document.documentElement;
        const nextDark = !root.classList.contains("dark");
        root.classList.toggle("dark", nextDark);
        try {
            window.localStorage.setItem(THEME_STORAGE_KEY, nextDark ? "dark" : "light");
        } catch (_) {
            /* localStorage disabled — theme will reset on reload. */
        }
        syncThemeIcons();
    }

    function bindThemeToggle() {
        const btn = document.getElementById("theme-toggle");
        if (!btn) return;
        btn.addEventListener("click", toggleTheme);
        syncThemeIcons();
    }

    /* -------------------------------------------------------------------- */
    /*  JWT injection — access token lives in sessionStorage after login.    */
    /* -------------------------------------------------------------------- */

    function getAccessToken() {
        try {
            return window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
        } catch (_) {
            return null;
        }
    }

    function setAccessToken(token) {
        try {
            if (token) {
                window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
            } else {
                window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
            }
        } catch (_) {
            /* sessionStorage disabled — JWT injection becomes a no-op. */
        }
    }

    function attachAuthHeader(evt) {
        const token = getAccessToken();
        if (!token) return;
        evt.detail.headers["Authorization"] = `Bearer ${token}`;
    }

    /* -------------------------------------------------------------------- */
    /*  htmx response handling: redirects + 401 + HX-Trigger flashes         */
    /* -------------------------------------------------------------------- */

    function handleResponse(evt) {
        const xhr = evt.detail.xhr;
        if (!xhr) return;

        // htmx already handles HX-Redirect / HX-Refresh natively, but we mirror
        // those headers for non-htmx fetches that may come through.
        const redirect = xhr.getResponseHeader("HX-Redirect") || xhr.getResponseHeader("X-Redirect");
        if (redirect) {
            window.location.assign(redirect);
            return;
        }
        const refresh = xhr.getResponseHeader("HX-Refresh");
        if (refresh && refresh.toLowerCase() === "true") {
            window.location.reload();
            return;
        }
        // Surface server flash events as toast bubbles.
        const trigger = xhr.getResponseHeader("HX-Trigger");
        if (trigger) {
            try {
                const parsed = JSON.parse(trigger);
                if (parsed && typeof parsed === "object" && parsed.flash) {
                    showFlash(parsed.flash);
                }
            } catch (_) {
                /* Trigger may be a plain event name; ignore. */
            }
        }
    }

    function handleResponseError(evt) {
        const xhr = evt.detail.xhr;
        if (!xhr) return;
        if (xhr.status === 401) {
            setAccessToken(null);
            window.location.assign("/admin/login");
            return;
        }
        if (xhr.status === 403) {
            showFlash({ kind: "error", message: "Permission denied." });
            return;
        }
        if (xhr.status >= 500) {
            showFlash({ kind: "error", message: "Server error — retry shortly." });
        }
    }

    function showFlash(payload) {
        const region = document.getElementById("flash");
        if (!region) return;
        const node = document.createElement("div");
        const kind = (payload && payload.kind) || "info";
        const palette = {
            info: "bg-slate-900 text-white",
            ok: "bg-emerald-600 text-white",
            warn: "bg-amber-600 text-white",
            error: "bg-rose-600 text-white",
        };
        node.className = `pointer-events-auto rounded-md px-3 py-2 text-sm shadow-lg ${palette[kind] || palette.info}`;
        node.textContent = (payload && payload.message) || "";
        node.setAttribute("role", "status");
        region.appendChild(node);
        window.setTimeout(() => node.remove(), 4000);
    }

    /* -------------------------------------------------------------------- */
    /*  Modal lifecycle: open on htmx swap, close on ESC / backdrop click.   */
    /* -------------------------------------------------------------------- */

    function openModal(modal) {
        modal.classList.remove("hidden");
        modal.classList.add("is-open", "flex");
        modal.setAttribute("aria-hidden", "false");
    }

    function closeModal(modal) {
        modal.classList.add("hidden");
        modal.classList.remove("is-open", "flex");
        modal.setAttribute("aria-hidden", "true");
        modal.innerHTML = "";
    }

    function bindModal() {
        const modal = document.getElementById("modal");
        if (!modal) return;

        document.body.addEventListener("htmx:afterSwap", (evt) => {
            if (evt.target && evt.target.id === "modal" && modal.innerHTML.trim() !== "") {
                openModal(modal);
            }
        });

        modal.addEventListener("click", (evt) => {
            if (evt.target === modal) closeModal(modal);
        });

        document.addEventListener("keydown", (evt) => {
            if (evt.key === "Escape" && !modal.classList.contains("hidden")) {
                closeModal(modal);
            }
        });
    }

    /* -------------------------------------------------------------------- */
    /*  Wiring                                                              */
    /* -------------------------------------------------------------------- */

    function bind() {
        bindThemeToggle();
        bindModal();
        document.body.addEventListener("htmx:configRequest", attachAuthHeader);
        document.body.addEventListener("htmx:beforeOnLoad", handleResponse);
        document.body.addEventListener("htmx:responseError", handleResponseError);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }

    // Export a tiny surface so the login page can hand us the access token
    // without reaching into private storage keys.
    function closeModalById() {
        const modal = document.getElementById("modal");
        if (modal) closeModal(modal);
    }

    window.adminShell = {
        setAccessToken,
        getAccessToken,
        toggleTheme,
        showFlash,
        closeModal: closeModalById,
    };
})();
