import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

import { clearTokens, readTokens, writeTokens } from "@/lib/token-store";
import { toNumber, toStringValue } from "@/lib/utils";
import type {
  AiPerformanceSummaryEntry,
  AuthTokenBundle,
  BacktestPayload,
  BacktestResult,
  GeneratePortfolioPayload,
  InstrumentSummary,
  PortfolioAllocation,
  PortfolioResult,
  RegisterPayload,
  RegisterResponse,
  StopRule,
  UserProfile,
  UserSession,
  WalletSummary,
} from "@/types/api";

declare module "axios" {
  interface AxiosRequestConfig {
    skipAuthRefresh?: boolean;
  }

  interface InternalAxiosRequestConfig {
    skipAuthRefresh?: boolean;
    _retry?: boolean;
  }
}

type AnyRecord = Record<string, unknown>;

const SESSION_ID_HEADER = "x-session-id";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL?.trim() || "http://localhost:8080/api/core";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

type FailedRequest = {
  resolve: (tokens: AuthTokenBundle) => void;
  reject: (error: unknown) => void;
};

let isRefreshing = false;
let failedQueue: FailedRequest[] = [];

function processQueue(error: unknown, tokens?: AuthTokenBundle) {
  failedQueue.forEach((request) => {
    if (error) {
      request.reject(error);
      return;
    }

    if (tokens) {
      request.resolve(tokens);
      return;
    }

    request.reject(new Error("Missing refreshed access token"));
  });

  failedQueue = [];
}

function getSessionIdFromHeaders(headers: unknown): string | undefined {
  if (!headers || typeof headers !== "object") {
    return undefined;
  }

  const source = headers as Record<string, unknown>;

  return (
    toStringValue(source[SESSION_ID_HEADER]) ||
    toStringValue(source["X-Session-Id"]) ||
    toStringValue(source["x-session-id"]) ||
    toStringValue(source["x_session_id"]) ||
    undefined
  );
}

function persistSessionIdFromHeaders(headers: unknown) {
  const sessionId = getSessionIdFromHeaders(headers);
  if (!sessionId) {
    return;
  }

  const tokens = readTokens();
  if (!tokens || tokens.sessionId === sessionId) {
    return;
  }

  writeTokens({
    ...tokens,
    sessionId,
  });
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
    sessionId: toStringValue(source.sessionId) ?? toStringValue(source.session_id),
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

  config.headers = config.headers ?? {};

  if (tokens?.accessToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${tokens.accessToken}`;
  }

  if (tokens?.sessionId && !config.headers["X-Session-Id"]) {
    config.headers["X-Session-Id"] = tokens.sessionId;
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => {
    persistSessionIdFromHeaders(response.headers);
    return response;
  },
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
          resolve: (tokens: AuthTokenBundle) => {
            originalRequest.headers = originalRequest.headers ?? {};
            originalRequest.headers.Authorization = `Bearer ${tokens.accessToken}`;
            if (tokens.sessionId) {
              originalRequest.headers["X-Session-Id"] = tokens.sessionId;
            }
            resolve(apiClient(originalRequest));
          },
          reject,
        });
      });
    }

    isRefreshing = true;

    try {
      const refreshPayload: Record<string, unknown> = {
        refreshToken: storedTokens.refreshToken,
      };

      if (storedTokens.sessionId) {
        refreshPayload.sessionId = storedTokens.sessionId;
      }

      const refreshResponse = await axios.post(
        `${API_BASE_URL}/auth/refresh`,
        refreshPayload,
        {
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
          },
          timeout: 20000,
          withCredentials: true,
        },
      );

      const refreshedTokens = normalizeTokenPayload(
        refreshResponse.data,
        storedTokens.refreshToken,
      );

      const sessionIdFromHeaders = getSessionIdFromHeaders(refreshResponse.headers);
      const rotatedTokens: AuthTokenBundle = {
        ...refreshedTokens,
        sessionId:
          refreshedTokens.sessionId || sessionIdFromHeaders || storedTokens.sessionId,
      };

      writeTokens(rotatedTokens);
      processQueue(null, rotatedTokens);

      originalRequest.headers = originalRequest.headers ?? {};
      originalRequest.headers.Authorization = `Bearer ${rotatedTokens.accessToken}`;
      if (rotatedTokens.sessionId) {
        originalRequest.headers["X-Session-Id"] = rotatedTokens.sessionId;
      }

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

const ApiContracts = {
  authRegister: "/auth/register",
  instrumentsReadModel: "/instruments",
  walletReadModel: (userId: number) => `/wallets/${userId}`,
  portfolioReadModel: (userId: number) => `/users/${userId}/portfolio/latest`,
  portfolioGenerate: "/portfolio/generate",
  portfolioRebalance: "/portfolio/allocate",
  aiPerformanceSummary: "/ai/performance-summary",
} as const;

function isRecord(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function getMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const responseMessage = (error.response?.data as AnyRecord | undefined)?.message;
    return toStringValue(responseMessage) || error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return "Unknown API error";
}

function shouldTryNextCandidate(error: unknown) {
  if (!axios.isAxiosError(error)) {
    return false;
  }

  const status = error.response?.status;
  return status === 404 || status === 405 || status === 400 || status === 415 || status === 422;
}

async function requestCandidates<T>(candidates: Array<() => Promise<T>>): Promise<T> {
  let lastError: unknown;

  for (const candidate of candidates) {
    try {
      return await candidate();
    } catch (error) {
      lastError = error;
      if (!shouldTryNextCandidate(error)) {
        throw error;
      }
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("No valid API candidate succeeded");
}

function normalizeAllocations(value: unknown): PortfolioAllocation[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .filter((item) => isRecord(item))
    .map((item) => ({
      stockId: toNumber(item.stockId) ?? toNumber(item.stock_id),
      symbol:
        toStringValue(item.symbol) ||
        toStringValue(item.ticker) ||
        toStringValue(item.code) ||
        "N/A",
      name: toStringValue(item.name) || toStringValue(item.companyName),
      sector: toStringValue(item.sector),
      weight: toNumber(item.weight),
      targetAmountEgp:
        toNumber(item.targetAmountEgp) ?? toNumber(item.target_amount_egp),
      priceSnapshot: toNumber(item.priceSnapshot) ?? toNumber(item.price_snapshot),
      executedShares: toNumber(item.executedShares) ?? toNumber(item.executed_shares),
      executedAmountEgp:
        toNumber(item.executedAmountEgp) ?? toNumber(item.executed_amount_egp),
      residualComponentEgp:
        toNumber(item.residualComponentEgp) ??
        toNumber(item.residual_component_egp),
      settlementStatus:
        toStringValue(item.settlementStatus) ||
        toStringValue(item.settlement_status),
    }));
}

function normalizePortfolioResult(raw: unknown): PortfolioResult {
  const data = isRecord(raw) ? raw : {};

  return {
    portfolioRunId:
      toNumber(data.portfolioRunId) ??
      toNumber(data.portfolio_run_id) ??
      toNumber(data.runId) ??
      toNumber(data.run_id),
    status: toStringValue(data.status) || toStringValue(data.runStatus),
    requestedAmount:
      toNumber(data.requestedAmount) ??
      toNumber(data.requested_amount) ??
      toNumber(data.requestedAmountEgp),
    feeBuffer: toNumber(data.feeBuffer) ?? toNumber(data.fee_buffer),
    investableBudget:
      toNumber(data.investableBudget) ?? toNumber(data.investable_budget),
    residualReturned:
      toNumber(data.residualReturned) ?? toNumber(data.residual_returned),
    expectedReturn: toNumber(data.expectedReturn) ?? toNumber(data.expected_return),
    expectedVolatility:
      toNumber(data.expectedVolatility) ?? toNumber(data.expected_volatility),
    modelVersion: toStringValue(data.modelVersion) || toStringValue(data.model_version),
    allocations:
      normalizeAllocations(data.allocations) ||
      normalizeAllocations(data.allocationExecutions),
    warnings: Array.isArray(data.warnings)
      ? data.warnings.filter((item): item is string => typeof item === "string")
      : [],
    rejectedSymbols: Array.isArray(data.rejectedSymbols)
      ? (data.rejectedSymbols as PortfolioResult["rejectedSymbols"])
      : Array.isArray(data.rejected_symbols)
        ? (data.rejected_symbols as PortfolioResult["rejectedSymbols"])
        : [],
  };
}

function normalizeBacktestResult(raw: unknown): BacktestResult {
  const data = isRecord(raw) ? raw : {};
  const allocationsRaw = Array.isArray(data.historicalAllocations)
    ? data.historicalAllocations
    : Array.isArray(data.historical_allocations)
      ? data.historical_allocations
      : [];

  return {
    requestId: toStringValue(data.requestId) || toStringValue(data.request_id),
    status: toStringValue(data.status),
    modelVersion: toStringValue(data.modelVersion) || toStringValue(data.model_version),
    historicalDate:
      toStringValue(data.historicalDate) || toStringValue(data.historical_date),
    originalValueEgp:
      toNumber(data.originalValueEgp) ?? toNumber(data.original_value_egp),
    currentValueEgp:
      toNumber(data.currentValueEgp) ?? toNumber(data.current_value_egp),
    roiPct: toNumber(data.roiPct) ?? toNumber(data.roi_pct),
    expectedReturn: toNumber(data.expectedReturn) ?? toNumber(data.expected_return),
    expectedVolatility:
      toNumber(data.expectedVolatility) ?? toNumber(data.expected_volatility),
    historicalAllocations: Array.isArray(allocationsRaw)
      ? allocationsRaw
          .filter((item) => isRecord(item))
          .map((item) => ({
            symbol: toStringValue(item.symbol) || "N/A",
            sector: toStringValue(item.sector),
            weight: toNumber(item.weight),
            historicalPrice:
              toNumber(item.historicalPrice) ?? toNumber(item.historical_price),
            currentPrice: toNumber(item.currentPrice) ?? toNumber(item.current_price),
            shares: toNumber(item.shares),
            allocatedValueEgp:
              toNumber(item.allocatedValueEgp) ?? toNumber(item.allocated_value_egp),
            currentValueEgp:
              toNumber(item.currentValueEgp) ?? toNumber(item.current_value_egp),
          }))
      : [],
    rejectedSymbols: Array.isArray(data.rejectedSymbols)
      ? (data.rejectedSymbols as BacktestResult["rejectedSymbols"])
      : Array.isArray(data.rejected_symbols)
        ? (data.rejected_symbols as BacktestResult["rejectedSymbols"])
        : [],
    warnings: Array.isArray(data.warnings)
      ? data.warnings.filter((item): item is string => typeof item === "string")
      : [],
  };
}

function normalizeAiPerformanceSummary(raw: unknown): AiPerformanceSummaryEntry[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  return raw
    .filter((item): item is AnyRecord => isRecord(item))
    .map((item) => {
      const parametersRaw = isRecord(item.optimizedParameters)
        ? item.optimizedParameters
        : isRecord(item.optimized_parameters)
          ? item.optimized_parameters
          : {};

      return {
        testDate: toStringValue(item.testDate) || toStringValue(item.test_date) || "",
        predictedReturn:
          toNumber(item.predictedReturn) ?? toNumber(item.predicted_return),
        actualReturn: toNumber(item.actualReturn) ?? toNumber(item.actual_return),
        accuracyScore:
          toNumber(item.accuracyScore) ?? toNumber(item.accuracy_score),
        bestSectorPrediction:
          toStringValue(item.bestSectorPrediction) ??
          toStringValue(item.best_sector_prediction) ??
          toStringValue(item.topSectorPrediction) ??
          toStringValue(item.top_sector_prediction) ??
          toStringValue(item.sector),
        optimizedParameters: {
          riskFreeRate:
            toNumber(parametersRaw.riskFreeRate) ??
            toNumber(parametersRaw.risk_free_rate),
          covarianceShrinkage:
            toNumber(parametersRaw.covarianceShrinkage) ??
            toNumber(parametersRaw.covariance_shrinkage),
        },
      };
    })
    .filter((entry) => entry.testDate.length > 0);
}

function normalizeInstruments(raw: unknown): InstrumentSummary[] {
  if (!Array.isArray(raw)) {
    return [];
  }

  return raw
    .filter((item): item is AnyRecord => isRecord(item))
    .map((item) => ({
      id: toNumber(item.id),
      symbol:
        toStringValue(item.symbol) ||
        toStringValue(item.ticker) ||
        toStringValue(item.code) ||
        "N/A",
      name: toStringValue(item.name) || toStringValue(item.companyName),
      sector:
        toStringValue(item.sector) ||
        toStringValue(item.sectorCode) ||
        toStringValue(item.sector_code),
      isin: toStringValue(item.isin),
      isSuspended: Boolean(item.isSuspended ?? item.is_suspended),
      lastPrice:
        toNumber(item.lastPrice) ??
        toNumber(item.last_price) ??
        toNumber(item.closePrice) ??
        toNumber(item.close_price),
      dayChangePct:
        toNumber(item.dayChangePct) ??
        toNumber(item.day_change_pct) ??
        toNumber(item.dailyChangePct) ??
        toNumber(item.changePct),
      volume: toNumber(item.volume),
    }))
    .filter((instrument) => instrument.symbol !== "N/A");
}

export async function loginUser(payload: {
  email: string;
  password: string;
}): Promise<AuthTokenBundle> {
  const response = await apiClient.post("/auth/login", payload, {
    skipAuthRefresh: true,
  });

  const normalizedTokens = normalizeTokenPayload(response.data);
  const sessionIdFromHeaders = getSessionIdFromHeaders(response.headers);

  return {
    ...normalizedTokens,
    sessionId: normalizedTokens.sessionId || sessionIdFromHeaders,
  };
}

export async function registerUser(payload: RegisterPayload): Promise<RegisterResponse> {
  const { data } = await apiClient.post(ApiContracts.authRegister, payload, {
    skipAuthRefresh: true,
  });
  return data;
}

export async function logoutUser() {
  try {
    await apiClient.post("/auth/logout", null);
  } catch {
    // Logout is best-effort. Token cleanup is handled by auth context.
  }
}

export async function fetchCurrentUser(): Promise<UserProfile> {
  const { data } = await apiClient.get("/users/me");
  const profile = isRecord(data) ? data : {};

  return {
    userId: toNumber(profile.userId) ?? toNumber(profile.user_id) ?? 0,
    email: toStringValue(profile.email) || "",
    fullName: toStringValue(profile.fullName) || toStringValue(profile.full_name) || "",
    phone: toStringValue(profile.phone) ?? null,
    tier: toStringValue(profile.tier) || "FREE",
    kycStatus: toStringValue(profile.kycStatus) || toStringValue(profile.kyc_status),
    accountStatus:
      toStringValue(profile.accountStatus) || toStringValue(profile.account_status),
    createdAt: toStringValue(profile.createdAt) || toStringValue(profile.created_at),
    updatedAt: toStringValue(profile.updatedAt) || toStringValue(profile.updated_at),
  };
}

export async function updateCurrentUser(payload: {
  fullName: string;
  phone?: string;
}): Promise<UserProfile> {
  const { data } = await apiClient.put("/users/me", payload);
  const profile = isRecord(data) ? data : {};

  return {
    userId: toNumber(profile.userId) ?? 0,
    email: toStringValue(profile.email) || "",
    fullName: toStringValue(profile.fullName) || "",
    phone: toStringValue(profile.phone) ?? null,
    tier: toStringValue(profile.tier) || "FREE",
    kycStatus: toStringValue(profile.kycStatus),
    accountStatus: toStringValue(profile.accountStatus),
    createdAt: toStringValue(profile.createdAt),
    updatedAt: toStringValue(profile.updatedAt),
  };
}

export async function fetchUserSessions(): Promise<UserSession[]> {
  const { data } = await apiClient.get("/users/me/sessions");
  if (!Array.isArray(data)) {
    return [];
  }

  return data
    .filter((item): item is AnyRecord => isRecord(item))
    .map((item) => ({
      sessionId: toNumber(item.sessionId) ?? toNumber(item.session_id) ?? 0,
      userAgent: toStringValue(item.userAgent) || toStringValue(item.user_agent) || "Unknown",
      ipAddress: toStringValue(item.ipAddress) || toStringValue(item.ip_address) || "-",
      lastActive: toStringValue(item.lastActive) || toStringValue(item.last_active) || "",
      expiresAt: toStringValue(item.expiresAt) || toStringValue(item.expires_at) || "",
      current: Boolean(item.current),
    }));
}

export async function revokeSession(sessionId: number) {
  await apiClient.delete(`/users/me/sessions/${sessionId}`);
}

export async function revokeOtherSessions() {
  await apiClient.delete("/users/me/sessions");
}

export async function fetchInstruments(): Promise<InstrumentSummary[]> {
  const data = await requestCandidates<unknown>([
    async () => (await apiClient.get(ApiContracts.instrumentsReadModel)).data,
    async () => (await apiClient.get("/market-data/instruments")).data,
    async () => (await apiClient.get("/premium/market-watch")).data,
  ]);

  return normalizeInstruments(data);
}

export async function fetchWalletSummary(userId: number): Promise<WalletSummary> {
  let data: unknown;

  try {
    const response = await apiClient.get(ApiContracts.walletReadModel(userId));
    data = response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      throw new Error(
        "Wallet read model endpoint is unavailable. Expected GET /wallets/{userId}.",
      );
    }

    throw error;
  }

  const source = isRecord(data)
    ? data
    : Array.isArray(data) && data.length > 0 && isRecord(data[0])
      ? data[0]
      : {};

  return {
    walletId: toNumber(source.walletId) ?? toNumber(source.wallet_id) ?? toNumber(source.id),
    userId: toNumber(source.userId) ?? toNumber(source.user_id) ?? userId,
    currency: toStringValue(source.currency) || "EGP",
    availableBalance:
      toNumber(source.availableBalance) ?? toNumber(source.available_balance),
    lockedBalance: toNumber(source.lockedBalance) ?? toNumber(source.locked_balance),
    updatedAt: toStringValue(source.updatedAt) || toStringValue(source.updated_at),
  };
}

export async function fetchLatestPortfolio(userId: number): Promise<PortfolioResult> {
  let data: unknown;

  try {
    const response = await apiClient.get(ApiContracts.portfolioReadModel(userId));
    data = response.data;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      throw new Error(
        "Portfolio read model endpoint is unavailable. Expected GET /users/{userId}/portfolio/latest.",
      );
    }

    throw error;
  }

  return normalizePortfolioResult(data);
}

export async function generatePortfolio(
  payload: GeneratePortfolioPayload,
): Promise<PortfolioResult> {
  const { data } = await apiClient.post(ApiContracts.portfolioGenerate, payload);

  return normalizePortfolioResult(data);
}

export async function executePortfolioRebalance(
  payload: GeneratePortfolioPayload,
): Promise<PortfolioResult> {
  const { data } = await apiClient.post(ApiContracts.portfolioRebalance, payload);

  return normalizePortfolioResult(data);
}

export async function runBacktest(payload: BacktestPayload): Promise<BacktestResult> {
  const { data } = await apiClient.post("/premium/backtest", payload);
  return normalizeBacktestResult(data);
}

export async function fetchAiPerformanceSummary(
  limit = 15,
): Promise<AiPerformanceSummaryEntry[]> {
  const sanitizedLimit = Math.min(20, Math.max(10, Math.trunc(limit)));

  try {
    const { data } = await apiClient.get(ApiContracts.aiPerformanceSummary, {
      params: { limit: sanitizedLimit },
    });

    return normalizeAiPerformanceSummary(data);
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 404) {
      throw new Error(
        "AI performance summary endpoint is unavailable. Expected GET /api/core/ai/performance-summary.",
      );
    }

    throw error;
  }
}

export async function fetchStopRules(): Promise<StopRule[]> {
  try {
    const data = await requestCandidates<unknown>([
      async () => (await apiClient.get("/premium/stop-rules")).data,
      async () => (await apiClient.get("/stop-rules")).data,
      async () => (await apiClient.get("/premium/market-watch")).data,
    ]);

    if (!Array.isArray(data)) {
      return [];
    }

    return data
      .filter((item): item is AnyRecord => isRecord(item))
      .map((item) => ({
        id: toNumber(item.id) ?? 0,
        userId: toNumber(item.userId) ?? toNumber(item.user_id),
        stockId: toNumber(item.stockId) ?? toNumber(item.stock_id),
        portfolioRunId:
          toNumber(item.portfolioRunId) ?? toNumber(item.portfolio_run_id),
        stopLossPct: toNumber(item.stopLossPct) ?? toNumber(item.stop_loss_pct),
        takeProfitPct:
          toNumber(item.takeProfitPct) ?? toNumber(item.take_profit_pct),
        isActive: Boolean(item.isActive ?? item.is_active),
        status: toStringValue(item.status),
      }));
  } catch {
    return [];
  }
}

export function mapApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const responseData = error.response?.data;
    if (isRecord(responseData)) {
      return (
        toStringValue(responseData.message) ||
        toStringValue(responseData.error) ||
        error.message
      );
    }

    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
  }

  return getMessage(error);
}
