import type { Role } from "./types";

export type ApiSurface = "admin" | "data";

export type ApiError = Error & {
  status?: number;
  payload?: unknown;
};

const ADMIN_BASE = import.meta.env.VITE_ADMIN_API_BASE ?? "http://127.0.0.1:7200";
const DATA_BASE = import.meta.env.VITE_DATA_API_BASE ?? "http://127.0.0.1:7000";

export const apiConfig = {
  adminBase: ADMIN_BASE,
  dataBase: DATA_BASE,
  adminWs:
    import.meta.env.VITE_ADMIN_WS_URL ??
    ADMIN_BASE.replace(/^http/, "ws").replace(/\/$/, "") + "/admin/events/stream"
};

export type AuthSnapshot = {
  token: string | null;
  role: Role | null;
  onUnauthorized: () => void;
};

let authSnapshot: AuthSnapshot = {
  token: null,
  role: null,
  onUnauthorized: () => undefined
};

export function setAuthSnapshot(next: AuthSnapshot): void {
  authSnapshot = next;
}

function resolveUrl(surface: ApiSurface, path: string, query?: Record<string, unknown>): string {
  const base = surface === "admin" ? ADMIN_BASE : DATA_BASE;
  const url = new URL(path, base);
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      if (Array.isArray(value)) {
        value.forEach((item) => url.searchParams.append(key, String(item)));
      } else {
        url.searchParams.set(key, String(value));
      }
    });
  }
  return url.toString();
}

export async function apiRequest<T>(
  surface: ApiSurface,
  path: string,
  options: {
    method?: string;
    query?: Record<string, unknown>;
    body?: unknown;
    signal?: AbortSignal;
    requireAuth?: boolean;
  } = {}
): Promise<T> {
  const method = options.method ?? (options.body === undefined ? "GET" : "POST");
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.requireAuth !== false && authSnapshot.token) {
    headers.set("Authorization", `Bearer ${authSnapshot.token}`);
  }

  const response = await fetch(resolveUrl(surface, path, options.query), {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: surface === "admin" ? "include" : "omit",
    signal: options.signal
  });

  if (response.status === 401) {
    authSnapshot.onUnauthorized();
  }

  if (!response.ok) {
    const error = new Error(`${method} ${path} failed with ${response.status}`) as ApiError;
    error.status = response.status;
    const text = await response.text();
    try {
      error.payload = text ? JSON.parse(text) : undefined;
    } catch {
      error.payload = text;
    }
    throw error;
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const adminGet = <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) =>
  apiRequest<T>("admin", path, { query, signal });

export const adminPost = <T>(path: string, body?: unknown) =>
  apiRequest<T>("admin", path, { method: "POST", body });

export const adminDelete = <T>(path: string) => apiRequest<T>("admin", path, { method: "DELETE" });

export const dataGet = <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) =>
  apiRequest<T>("data", path, { query, signal });

export function isMasterAdmin(role: Role | null): boolean {
  return role === "MASTER_ADMIN";
}
