# Multi-Channel Messenger Platform

Production-ready multi-channel messaging platform with support for Telegram, VK, WhatsApp, and MAX.

## Stack

**Backend:**
- Python 3.12, FastAPI, Uvicorn
- Pydantic v2, SQLAlchemy 2.0 asyncpg
- Alembic, PostgreSQL 15+, Redis 7+
- ARQ, aioredis, S3/MinIO, ClamAV

**Frontend:**
- Next.js 14, TypeScript 5+
- Tailwind, shadcn/ui
- Zustand, TanStack Query/Virtual

**DevOps:**
- Docker, Traefik, GitHub Actions
- Sentry, Prometheus, Grafana

## Project Structure

```
backend/
├── domain/           # Business logic, aggregates, value objects
├── application/      # Commands, queries, interfaces, DTOs
├── infrastructure/   # DB, cache, channels, auth, workers, events
└── presentation/     # API, WebSocket, middleware, schemas

frontend/
├── app/              # Next.js App Router pages
├── components/       # UI components
├── lib/              # Utilities, API clients, hooks
└── stores/           # Zustand stores

docker/               # Dockerfiles for services
tests/                # Unit, integration, E2E tests
deploy/               # Deployment configurations
```

## Quick Start

```bash
# Start all services
docker-compose up -d

# Run migrations
docker-compose exec fastapi alembic upgrade head

# Access frontend
http://localhost:3000

# Access backend API
http://localhost:8000/api/v1/health
```

## Features

- **Multi-channel support**: Telegram, VK, WhatsApp (Meta Cloud), MAX
- **Real-time messaging**: WebSocket with horizontal scaling via Redis pub/sub
- **Offline-first**: IndexedDB queue with conflict resolution
- **Security**: CSRF protection, ClamAV scanning, JWT rotation
- **Observability**: Sentry, Prometheus metrics, structured logging
- **High availability**: Circuit breakers, rate limiting, retry logic

## License

MIT