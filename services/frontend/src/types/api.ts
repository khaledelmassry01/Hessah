export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

export interface AuthTokenBundle {
  userId: number;
  tier: string;
  sessionId?: string;
  accessToken: string;
  accessTokenExpiresAt?: string | null;
  refreshToken: string;
  refreshTokenExpiresAt?: string | null;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  email: string;
  password: string;
  fullName: string;
  phone?: string;
}

export interface RegisterResponse {
  userId: number;
  email: string;
  fullName: string;
  tier: string;
  message?: string;
}

export interface UserProfile {
  userId: number;
  email: string;
  fullName: string;
  phone?: string | null;
  tier: string;
  kycStatus?: string;
  accountStatus?: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface UserSession {
  sessionId: number;
  userAgent: string;
  ipAddress: string;
  lastActive: string;
  expiresAt: string;
  current: boolean;
}

export interface WalletSummary {
  walletId?: number;
  userId?: number;
  currency?: string;
  availableBalance?: number;
  lockedBalance?: number;
  updatedAt?: string;
}

export interface InstrumentSummary {
  id?: number;
  symbol: string;
  name?: string;
  sector?: string;
  isin?: string;
  isSuspended?: boolean;
  lastPrice?: number;
  dayChangePct?: number;
  volume?: number;
}

export interface PortfolioAllocation {
  stockId?: number;
  symbol: string;
  name?: string;
  sector?: string;
  weight?: number;
  targetAmountEgp?: number;
  priceSnapshot?: number;
  executedShares?: number;
  executedAmountEgp?: number;
  residualComponentEgp?: number;
  settlementStatus?: string;
}

export interface RejectedSymbol {
  symbol: string;
  reason: string;
}

export interface PortfolioResult {
  portfolioRunId?: number;
  status?: string;
  requestedAmount?: number;
  feeBuffer?: number;
  investableBudget?: number;
  residualReturned?: number;
  expectedReturn?: number;
  expectedVolatility?: number;
  modelVersion?: string;
  allocations: PortfolioAllocation[];
  warnings?: string[];
  rejectedSymbols?: RejectedSymbol[];
}

export interface GeneratePortfolioPayload {
  userId: number;
  amount: number;
  riskLevel: RiskLevel;
  sectorConstraints?: string[];
}

export interface BacktestPayload {
  userId: number;
  budgetEgp: number;
  historicalDate: string;
  riskLevel: RiskLevel;
  maxSectorWeight?: number;
  maxAdv30Participation?: number;
  excludeSuspended?: boolean;
  allowFractionalShares?: boolean;
}

export interface BacktestAllocation {
  symbol: string;
  sector?: string;
  weight?: number;
  historicalPrice?: number;
  currentPrice?: number;
  shares?: number;
  allocatedValueEgp?: number;
  currentValueEgp?: number;
}

export interface BacktestResult {
  requestId?: string;
  status?: string;
  modelVersion?: string;
  historicalDate?: string;
  originalValueEgp?: number;
  currentValueEgp?: number;
  roiPct?: number;
  expectedReturn?: number;
  expectedVolatility?: number;
  historicalAllocations: BacktestAllocation[];
  rejectedSymbols?: RejectedSymbol[];
  warnings?: string[];
}

export interface AiPerformanceSummaryEntry {
  testDate: string;
  predictedReturn?: number;
  actualReturn?: number;
  accuracyScore?: number;
  bestSectorPrediction?: string;
  optimizedParameters?: {
    riskFreeRate?: number;
    covarianceShrinkage?: number;
  };
}

export interface StopRule {
  id: number;
  userId?: number;
  stockId?: number;
  portfolioRunId?: number;
  stopLossPct?: number;
  takeProfitPct?: number;
  isActive?: boolean;
  status?: string;
}

export interface ApiError {
  message: string;
  status?: number;
}
