import type { Role } from "./types";

export type ApiSurface = "admin" | "data";

export type ApiError = Error & {
  status?: number;
  payload?: unknown;
};

const ADMIN_BASE = import.meta.env.VITE_ADMIN_API_BASE ?? "/admin-api";
const DATA_BASE = import.meta.env.VITE_DATA_API_BASE ?? "/admin-api/admin/dataapi";

function defaultAdminWsUrl(): string {
  if (typeof window === "undefined") return "ws://127.0.0.1:7200/admin/events/stream";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/admin-ws/admin/events/stream`;
}

export const apiConfig = {
  adminBase: ADMIN_BASE,
  dataBase: DATA_BASE,
  adminWs: import.meta.env.VITE_ADMIN_WS_URL ?? defaultAdminWsUrl()
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
  const absoluteBase =
    base.startsWith("http://") || base.startsWith("https://")
      ? base
      : `${window.location.origin}${base.startsWith("/") ? base : `/${base}`}`;
  const url = new URL(`${absoluteBase.replace(/\/$/, "")}${path}`);
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
    notifyUnauthorized?: boolean;
  } = {}
): Promise<T> {
  const method = options.method ?? (options.body === undefined ? "GET" : "POST");
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  const requestToken = authSnapshot.token;
  if (options.requireAuth !== false && requestToken) {
    headers.set("Authorization", `Bearer ${requestToken}`);
  }

  const response = await fetch(resolveUrl(surface, path, options.query), {
    method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    credentials: surface === "admin" ? "include" : "omit",
    signal: options.signal
  });

  if (
    response.status === 401 &&
    surface === "admin" &&
    options.notifyUnauthorized !== false &&
    requestToken &&
    requestToken === authSnapshot.token
  ) {
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

export const adminPostWithHeaders = async <T>(
  path: string,
  body: unknown,
  extraHeaders: Record<string, string>
): Promise<T> => {
  const method = "POST";
  const requestToken = authSnapshot.token;
  const headers = new Headers(extraHeaders);
  headers.set("Content-Type", "application/json");
  if (requestToken) headers.set("Authorization", `Bearer ${requestToken}`);

  const response = await fetch(resolveUrl("admin", path), {
    method,
    headers,
    body: JSON.stringify(body),
    credentials: "include"
  });

  if (response.status === 401 && requestToken && requestToken === authSnapshot.token) {
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
};

export const adminAuthPost = <T>(path: string, body?: unknown) =>
  apiRequest<T>("admin", path, {
    method: "POST",
    body,
    requireAuth: false,
    notifyUnauthorized: false
  });

export const adminDelete = <T>(path: string) => apiRequest<T>("admin", path, { method: "DELETE" });

export const dataGet = <T>(path: string, query?: Record<string, unknown>, signal?: AbortSignal) =>
  apiRequest<T>("data", path, { query, signal });

export function isMasterAdmin(role: Role | null): boolean {
  return role === "MASTER_ADMIN";
}
