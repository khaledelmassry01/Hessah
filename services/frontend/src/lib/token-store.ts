import type { AuthTokenBundle } from "@/types/api";

let memoryCache: AuthTokenBundle | null | undefined;

function isValidTokenBundle(value: unknown): value is AuthTokenBundle {
  if (!value || typeof value !== "object") {
    return false;
  }

  const token = value as Partial<AuthTokenBundle>;
  return (
    typeof token.userId === "number" &&
    typeof token.tier === "string" &&
    typeof token.role === "string" &&
    typeof token.accessToken === "string" &&
    typeof token.refreshToken === "string"
  );
}

export function readTokens(): AuthTokenBundle | null {
  if (memoryCache !== undefined) {
    return memoryCache;
  }
  memoryCache = null;
  return null;
}

export function writeTokens(tokens: AuthTokenBundle) {
  memoryCache = isValidTokenBundle(tokens) ? tokens : null;
}

export function clearTokens() {
  memoryCache = null;
}
