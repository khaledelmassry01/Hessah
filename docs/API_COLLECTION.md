# EGX Portfolio Optimizer - API Handover Collection (Markdown)

This document is a Postman-style handover contract for the frontend team.

## Base URLs

- API Gateway (preferred): `http://localhost:8080/api/core`
- Core Backend direct: `http://localhost:8081`
- AI Engine direct (for diagnostics): `http://localhost:8000`

## Authentication

- For local development in this repository, auth enforcement can be disabled with:
  - `APP_SECURITY_REQUIRE_AUTH=false`
- When auth is enabled, provide JWT bearer token:
  - Header: `Authorization: Bearer <jwt-token>`

---

## 1) Register / Login (Auth)

### 1.1 Register User

```bash
curl -X POST "http://localhost:8080/api/core/users/register" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "frontend.user@example.com",
    "password": "StrongPass#2026",
    "fullName": "Frontend User"
  }'
```

Example response:

```json
{
  "userId": 101,
  "email": "frontend.user@example.com",
  "status": "ACTIVE",
  "createdAt": "2026-04-19T15:00:00Z"
}
```

### 1.2 Login

```bash
curl -X POST "http://localhost:8080/api/core/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "frontend.user@example.com",
    "password": "StrongPass#2026"
  }'
```

Example response:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "userId": 101
}
```

---

## 2) Fund Wallet

```bash
curl -X POST "http://localhost:8080/api/core/wallet/fund" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "amountEgp": 500000
  }'
```

Example response:

```json
{
  "walletId": 25,
  "userId": 101,
  "currency": "EGP",
  "availableBalance": 500000.0,
  "lockedBalance": 0.0,
  "updatedAt": "2026-04-19T15:10:00Z"
}
```

---

## 3) Request Predict (Free / Low Risk)

```bash
curl -X POST "http://localhost:8080/api/core/portfolio/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "amount": 50000,
    "riskLevel": "LOW"
  }'
```

Example response:

```json
{
  "portfolioRunId": 3001,
  "status": "COMPLETED",
  "requestedAmount": 50000.0,
  "feeBuffer": 250.0,
  "investableBudget": 49750.0,
  "modelVersion": "mpt-egx30-v3",
  "allocations": [
    {
      "symbol": "COMI",
      "sector": "BANKS",
      "executedShares": 210,
      "executedAmountEgp": 12084.0,
      "residualComponentEgp": 116.0
    }
  ]
}
```

---

## 4) Upgrade Tier to Premium

```bash
curl -X POST "http://localhost:8080/api/core/subscriptions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "tier": "PREMIUM",
    "status": "ACTIVE"
  }'
```

Example response:

```json
{
  "subscriptionId": 700,
  "userId": 101,
  "tier": "PREMIUM",
  "status": "ACTIVE",
  "startedAt": "2026-04-19T15:12:00Z"
}
```

---

## 5) Request Predict (Premium / High Risk)

```bash
curl -X POST "http://localhost:8080/api/core/portfolio/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "amount": 500000,
    "riskLevel": "HIGH"
  }'
```

Example response:

```json
{
  "portfolioRunId": 3002,
  "status": "PARTIAL",
  "requestedAmount": 500000.0,
  "feeBuffer": 2500.0,
  "investableBudget": 497500.0,
  "residualReturned": 352.4,
  "modelVersion": "mpt-egx30-v3",
  "expectedReturn": 0.2431,
  "expectedVolatility": 0.1988,
  "allocations": [
    {
      "symbol": "HRHO",
      "sector": "FINANCIAL_SERVICES",
      "executedShares": 1450,
      "executedAmountEgp": 80285.0,
      "settlementStatus": "PENDING"
    }
  ]
}
```

---

## 6) Generate Tear-Sheet

```bash
curl -X GET "http://localhost:8080/api/core/premium/tear-sheet/3002" \
  -H "Authorization: Bearer <jwt-token>"
```

Example response:

```json
{
  "portfolioRunId": 3002,
  "userId": 101,
  "modelVersion": "mpt-egx30-v3",
  "runStatus": "PARTIAL",
  "requestedAmount": 500000.0,
  "totalInvested": 495000.0,
  "feeBuffer": 2500.0,
  "residualCash": 2500.0,
  "expectedRoi": 0.2431,
  "assets": [
    {
      "symbol": "COMI",
      "sector": "BANKS",
      "shares": 2200,
      "totalPrice": 126720.0
    }
  ]
}
```

---

## 7) Request Backtest

```bash
curl -X POST "http://localhost:8080/api/core/premium/backtest" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "budgetEgp": 500000,
    "historicalDate": "2025-10-19",
    "riskLevel": "HIGH",
    "maxSectorWeight": 0.4,
    "maxAdv30Participation": 0.05,
    "excludeSuspended": true,
    "allowFractionalShares": false
  }'
```

Example response:

```json
{
  "request_id": "b9f3fd27-0f7f-4d07-8d24-ec9e0bb7f556",
  "status": "PARTIAL",
  "model_version": "mpt-egx30-backtest-v1",
  "historical_date": "2025-10-19",
  "original_value_egp": 500000.0,
  "current_value_egp": 558430.75,
  "roi_pct": 11.68615,
  "expected_return": 0.2513,
  "expected_volatility": 0.2094,
  "historical_allocations": [
    {
      "symbol": "SWDY",
      "sector": "INDUSTRIALS",
      "weight": 0.14233121,
      "historical_price": 52.44,
      "current_price": 59.18,
      "shares": 1357.0,
      "allocated_value_egp": 71161.08,
      "current_value_egp": 80307.26
    }
  ],
  "rejected_symbols": [
    {
      "symbol": "ABCX",
      "reason": "LIQUIDITY_CAP"
    }
  ],
  "warnings": []
}
```

---

## 8) Set Stop-Loss / Take-Profit Rule

```bash
curl -X POST "http://localhost:8080/api/core/premium/stop-rules" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "userId": 101,
    "stockId": 1,
    "portfolioRunId": 3002,
    "stopLossPct": 0.1,
    "takeProfitPct": 0.2,
    "isActive": true
  }'
```

Example response:

```json
{
  "id": 910,
  "userId": 101,
  "stockId": 1,
  "portfolioRunId": 3002,
  "stopLossPct": 0.1,
  "takeProfitPct": 0.2,
  "isActive": true
}
```

---

## Notes for Frontend Mocking

- Monetary fields are in EGP and should be rendered with 4 decimal precision where needed.
- For statuses, expect: `SUCCESS`, `PARTIAL`, `FAILED`.
- For premium-restricted operations (`/premium/**`), show an access upgrade prompt on HTTP `403`.
- Backtest and Predict can return `warnings` and `rejected_symbols`; UI should show these non-blocking diagnostics.
