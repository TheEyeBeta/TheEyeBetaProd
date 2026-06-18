import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { adminPost, setAuthSnapshot } from "../api/http";
import type { CurrentUserResponse, LoginResponse, RefreshResponse, Role } from "../api/types";

type AuthState = {
  token: string | null;
  role: Role | null;
  username: string | null;
  bootstrapped: boolean;
};

type LoginResult =
  | { status: "authenticated" }
  | { status: "mfa_required"; mfaToken: string }
  | { status: "enrollment_required"; enrollmentToken?: string };

type AuthContextValue = AuthState & {
  login: (username: string, password: string, totp?: string) => Promise<LoginResult>;
  verifyMfa: (mfaToken: string, totp: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function extractUser(response: LoginResponse | RefreshResponse | CurrentUserResponse) {
  return {
    token: "access_token" in response ? (response.access_token ?? null) : null,
    role: response.role ?? null,
    username: response.username ?? ("username" in response ? response.username : null) ?? null
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: null,
    role: null,
    username: null,
    bootstrapped: false
  });

  const clear = useCallback(() => {
    setState({ token: null, role: null, username: null, bootstrapped: true });
  }, []);

  useEffect(() => {
    setAuthSnapshot({ token: state.token, role: state.role, onUnauthorized: clear });
  }, [clear, state.role, state.token]);

  useEffect(() => {
    let live = true;
    adminPost<RefreshResponse>("/admin/auth/refresh")
      .then((response) => {
        if (!live) return;
        const user = extractUser(response);
        setState({
          token: user.token,
          role: user.role,
          username: user.username,
          bootstrapped: true
        });
      })
      .catch(() => {
        if (live) clear();
      });
    return () => {
      live = false;
    };
  }, [clear]);

  const applyToken = useCallback((response: LoginResponse | RefreshResponse) => {
    const user = extractUser(response);
    if (!user.token || !user.role) throw new Error("Auth response did not include token/role");
    setState({ token: user.token, role: user.role, username: user.username, bootstrapped: true });
  }, []);

  const login = useCallback(
    async (username: string, password: string, totp?: string): Promise<LoginResult> => {
      const response = await adminPost<LoginResponse>("/admin/auth/login", {
        username,
        password,
        totp_code: totp || undefined
      });
      if (response.mfa_required && response.mfa_token) {
        return { status: "mfa_required", mfaToken: response.mfa_token };
      }
      if (response.enrollment_required) {
        return { status: "enrollment_required", enrollmentToken: response.enrollment_token };
      }
      applyToken(response);
      return { status: "authenticated" };
    },
    [applyToken]
  );

  const verifyMfa = useCallback(
    async (mfaToken: string, totp: string) => {
      const response = await adminPost<LoginResponse>("/admin/auth/mfa/verify", {
        mfa_token: mfaToken,
        totp_code: totp
      });
      applyToken(response);
    },
    [applyToken]
  );

  const logout = useCallback(async () => {
    try {
      await adminPost<void>("/admin/auth/logout");
    } finally {
      clear();
    }
  }, [clear]);

  const value = useMemo(
    () => ({ ...state, login, verifyMfa, logout }),
    [login, logout, state, verifyMfa]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
