# EGX Portfolio Optimizer

A production-oriented portfolio optimization platform for the Egyptian Exchange (EGX), combining:

- Java Spring Boot Core Backend (business orchestration, premium features, persistence, security)
- Python FastAPI AI Engine (allocation optimization, constraints, historical backtesting)
- API Gateway for unified routing
- MySQL for transactional and audit data

## Project Overview

This repository delivers an end-to-end flow for investment portfolio generation and premium analytics:

- Wallet funding and portfolio request lifecycle
- Free and premium optimization paths
- AI model allocation with EGX data ingestion
- Premium tear-sheet and historical backtesting
- Stop-loss / take-profit rule management and monitoring

## High-Level Architecture

- `services/core-backend`
  - Spring Boot 3.3.5 (Java 17)
  - REST APIs, domain services, Flyway migrations, scheduler, premium controls
- `services/ai-engine`
  - FastAPI
  - Mean-variance optimization, constraints, and backtesting pipeline
- `services/api-gateway`
  - Entry-point routing for frontend and client consumers
- `infra/docker-compose.yml`
  - Local full-stack orchestration

## Prerequisites

Install the following tools:

- Docker Desktop (latest stable, Compose v2)
- Python 3.10+ (for local E2E test script)
- `pip`

Optional for local non-container development:

- Java 17
- Maven 3.9+

## Run the Full System with Docker Compose

From repository root:

```bash
cd infra
docker compose up --build -d
```

Check service status:

```bash
docker compose ps
```

Expected exposed ports:

- API Gateway: `8080`
- Core Backend: `8081`
- AI Engine: `8000`
- MySQL: `3306`

### Stop the stack

```bash
cd infra
docker compose down
```

To remove volumes too:

```bash
cd infra
docker compose down -v
```

## API Documentation (Swagger / OpenAPI)

After services are up:

- Swagger UI: `http://localhost:8081/swagger-ui/index.html`
- OpenAPI JSON: `http://localhost:8081/v3/api-docs`

JWT bearer scheme is preconfigured in OpenAPI so frontend teams can authorize directly from Swagger UI.

## Frontend/API Handover Contracts

A Postman-style markdown collection with cURL examples and mock request/response payloads is available in:

- `docs/API_COLLECTION.md`

This includes the critical E2E journey:

1. Register/Login
2. Fund Wallet
3. Predict (Free / Low Risk)
4. Upgrade to Premium
5. Predict (Premium / High Risk)
6. Tear-Sheet
7. Backtest
8. Stop-Loss/Take-Profit Rules

## Run E2E Health Verification Script

From repository root:

```bash
python e2e_flow_test.py
```

If needed, install script dependencies first:

```bash
pip install requests
```

The script validates key journey behavior and verifies portfolio generation and premium flows end-to-end.

## Troubleshooting

- If containers fail to start, inspect logs:

```bash
cd infra
docker compose logs -f
```

- If AI engine dependency installation fails in local environment, use Dockerized execution first (`docker compose up --build`) to ensure clean dependency resolution.

## License / Client Handover

This repository is prepared for client handover with production-readiness artifacts:

- OpenAPI/Swagger documentation
- Security + CORS configuration baseline
- Frontend contract markdown collection
- Dockerized startup and E2E verification instructions
