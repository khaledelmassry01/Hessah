import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import { clearTokens, readTokens, writeTokens } from "@/lib/token-store";
import { toNumber, toStringValue } from "@/lib/utils";
import type { AuthTokenBundle } from "@/types/api";

declare module "axios" {
  interface AxiosRequestConfig {
    skipAuthRefresh?: boolean;
  }

  interface InternalAxiosRequestConfig {
    skipAuthRefresh?: boolean;
    _retry?: boolean;
  }
}

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || "/api/core";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

type FailedRequest = {
  resolve: (token: string) => void;
  reject: (error: unknown) => void;
};

let isRefreshing = false;
let failedQueue: FailedRequest[] = [];

function processQueue(error: unknown, token?: string) {
  failedQueue.forEach((request) => {
    if (error) {
      request.reject(error);
      return;
    }

    if (token) {
      request.resolve(token);
      return;
    }

    request.reject(new Error("Missing refreshed access token"));
  });

  failedQueue = [];
}

function isPublicAuthRequest(url?: string) {
  if (!url) {
    return false;
  }

  return ["/auth/login", "/auth/register", "/auth/refresh"].some((endpoint) =>
    url.includes(endpoint),
  );
}

export function normalizeTokenPayload(
  payload: unknown,
  fallbackRefreshToken?: string,
): AuthTokenBundle {
  const source = (payload as Record<string, unknown>) || {};

  const userId =
    toNumber(source.userId) ??
    toNumber(source.user_id) ??
    toNumber(source.id) ??
    0;

  const tier =
    toStringValue(source.tier) ??
    toStringValue(source.subscriptionTier) ??
    "FREE";

  const role =
    toStringValue(source.role) ??
    "USER";

  const accessToken =
    toStringValue(source.accessToken) ??
    toStringValue(source.access_token) ??
    toStringValue(source.token) ??
    toStringValue(source.jwt);

  const refreshToken =
    toStringValue(source.refreshToken) ??
    toStringValue(source.refresh_token) ??
    fallbackRefreshToken;

  if (!accessToken) {
    throw new Error("Access token is missing in auth response");
  }

  if (!refreshToken) {
    throw new Error("Refresh token is missing in auth response");
  }

  return {
    userId,
    tier,
    role,
    accessToken,
    refreshToken,
    accessTokenExpiresAt:
      toStringValue(source.accessTokenExpiresAt) ??
      toStringValue(source.access_token_expires_at) ??
      null,
    refreshTokenExpiresAt:
      toStringValue(source.refreshTokenExpiresAt) ??
      toStringValue(source.refresh_token_expires_at) ??
      null,
  };
}

apiClient.interceptors.request.use((config) => {
  const tokens = readTokens();

  if (tokens?.accessToken) {
    config.headers = config.headers ?? {};
    if (!config.headers.Authorization) {
      config.headers.Authorization = `Bearer ${tokens.accessToken}`;
    }
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig | undefined;
    const status = error.response?.status;

    if (!originalRequest || status !== 401) {
      return Promise.reject(error);
    }

    if (originalRequest.skipAuthRefresh || isPublicAuthRequest(originalRequest.url)) {
      return Promise.reject(error);
    }

    const storedTokens = readTokens();
    if (!storedTokens?.refreshToken) {
      clearTokens();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("auth:logout"));
      }
      return Promise.reject(error);
    }

    if (originalRequest._retry) {
      return Promise.reject(error);
    }

    originalRequest._retry = true;

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token: string) => {
            originalRequest.headers = originalRequest.headers ?? {};
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(apiClient(originalRequest));
          },
          reject,
        });
      });
    }

    isRefreshing = true;

    try {
      const refreshResponse = await axios.post(
        `${API_BASE_URL}/auth/refresh`,
        { refreshToken: storedTokens.refreshToken },
        {
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          timeout: 20000,
        },
      );

      const rotatedTokens = normalizeTokenPayload(
        refreshResponse.data,
        storedTokens.refreshToken,
      );

      writeTokens(rotatedTokens);
      processQueue(null, rotatedTokens.accessToken);

      originalRequest.headers = originalRequest.headers ?? {};
      originalRequest.headers.Authorization = `Bearer ${rotatedTokens.accessToken}`;

      return apiClient(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError);
      clearTokens();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new CustomEvent("auth:logout"));
      }
      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  },
);
