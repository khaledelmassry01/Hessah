import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  fetchCurrentUser,
  loginUser,
  logoutUser,
  mapApiError,
  registerUser,
} from "@/lib/api";
import { clearTokens, readTokens, writeTokens } from "@/lib/token-store";
import type {
  AuthTokenBundle,
  LoginPayload,
  RegisterPayload,
  UserProfile,
} from "@/types/api";

type AuthContextValue = {
  user: UserProfile | null;
  tokens: AuthTokenBundle | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  isPremium: boolean;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
  refreshProfile: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [tokens, setTokens] = useState<AuthTokenBundle | null>(null);
  const [isInitializing, setIsInitializing] = useState(true);

  const clearAuthState = useCallback(() => {
    clearTokens();
    setTokens(null);
    setUser(null);
  }, []);

  const hydrateFromTokens = useCallback(async (tokenBundle: AuthTokenBundle) => {
    writeTokens(tokenBundle);
    setTokens(tokenBundle);

    const profile = await fetchCurrentUser();
    setUser(profile);

    if (profile.userId && profile.userId !== tokenBundle.userId) {
      const nextTokens = { ...tokenBundle, userId: profile.userId, tier: profile.tier };
      writeTokens(nextTokens);
      setTokens(nextTokens);
    } else if (profile.tier && profile.tier !== tokenBundle.tier) {
      const nextTokens = { ...tokenBundle, tier: profile.tier };
      writeTokens(nextTokens);
      setTokens(nextTokens);
    }
  }, []);

  const refreshProfile = useCallback(async () => {
    const profile = await fetchCurrentUser();
    setUser(profile);

    const currentTokens = readTokens();
    if (currentTokens) {
      const nextTokens = {
        ...currentTokens,
        userId: profile.userId || currentTokens.userId,
        tier: profile.tier || currentTokens.tier,
      };
      writeTokens(nextTokens);
      setTokens(nextTokens);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const stored = readTokens();
      if (stored) {
        try {
          await hydrateFromTokens(stored);
        } catch {
          clearAuthState();
        } finally {
          if (!cancelled) {
            setIsInitializing(false);
          }
        }

        return;
      }

      try {
        const profile = await fetchCurrentUser();
        if (!cancelled) {
          setUser(profile);
          setIsInitializing(false);
        }
      } catch {
        if (!cancelled) {
          clearAuthState();
        }
      } finally {
        if (!cancelled) {
          setIsInitializing(false);
        }
      }
    }

    bootstrap();

    const onForcedLogout = () => {
      clearAuthState();
    };

    window.addEventListener("auth:logout", onForcedLogout);

    return () => {
      cancelled = true;
      window.removeEventListener("auth:logout", onForcedLogout);
    };
  }, [clearAuthState, hydrateFromTokens]);

  const login = useCallback(
    async (payload: LoginPayload) => {
      try {
        const tokenBundle = await loginUser(payload);
        await hydrateFromTokens(tokenBundle);
      } catch (error) {
        throw new Error(mapApiError(error));
      }
    },
    [hydrateFromTokens],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      try {
        await registerUser(payload);
        const tokenBundle = await loginUser({
          email: payload.email,
          password: payload.password,
        });
        await hydrateFromTokens(tokenBundle);
      } catch (error) {
        throw new Error(mapApiError(error));
      }
    },
    [hydrateFromTokens],
  );

  const logout = useCallback(async () => {
    try {
      await logoutUser();
    } finally {
      clearAuthState();
    }
  }, [clearAuthState]);

  const isAuthenticated = Boolean(user) || Boolean(tokens?.accessToken);
  const tier = (user?.tier || tokens?.tier || "FREE").toUpperCase();
  const isPremium = tier === "PREMIUM";

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      tokens,
      isAuthenticated,
      isInitializing,
      isPremium,
      login,
      register,
      logout,
      refreshProfile,
    }),
    [
      user,
      tokens,
      isAuthenticated,
      isInitializing,
      isPremium,
      login,
      register,
      logout,
      refreshProfile,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }

  return context;
}
