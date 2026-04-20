import type { AuthTokenBundle } from "@/types/api";

const STORAGE_KEY = "egx.auth.tokens";
let memoryCache: AuthTokenBundle | null | undefined;

function canUseStorage() {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function isValidTokenBundle(value: unknown): value is AuthTokenBundle {
  if (!value || typeof value !== "object") {
    return false;
  }

  const token = value as Partial<AuthTokenBundle>;
  return (
    typeof token.userId === "number" &&
    typeof token.tier === "string" &&
    typeof token.accessToken === "string" &&
    typeof token.refreshToken === "string"
  );
}

export function readTokens(): AuthTokenBundle | null {
  if (memoryCache !== undefined) {
    return memoryCache;
  }

  if (!canUseStorage()) {
    memoryCache = null;
    return null;
  }

  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    memoryCache = null;
    return null;
  }

  try {
    const parsed = JSON.parse(raw);
    if (isValidTokenBundle(parsed)) {
      memoryCache = parsed;
      return parsed;
    }
  } catch {
    // no-op
  }

  memoryCache = null;
  window.localStorage.removeItem(STORAGE_KEY);
  return null;
}

export function writeTokens(tokens: AuthTokenBundle) {
  memoryCache = tokens;
  if (canUseStorage()) {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
  }
}

export function clearTokens() {
  memoryCache = null;
  if (canUseStorage()) {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}
