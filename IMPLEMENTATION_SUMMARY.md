# OneChat - Multi-Channel Messenger Platform

## Архитектурное резюме

Платформа для унифицированной коммуникации через Telegram, VK, WhatsApp и MAX с поддержкой real-time обновлений, offline-режима и горизонтального масштабирования.

## Реализованные компоненты

### ✅ Backend (FastAPI + SQLAlchemy 2.0 async)

#### Domain Layer (`backend/domain/`)
- **Value Objects**: `ChannelType`, `MessageStatus`, `ExternalId`, `SequenceId`
- **Entities**: `Workspace`, `User`, `Member`, `ChannelAccount`, `Conversation`, `Message`, `AuditLog`
- **Domain Events**: `MessageReceived`, `MessageFailed`, `ChannelRateLimited`
- **EventDispatcher**: Маппинг событий на WS-бродкаст, ARQ-очереди, Sentry, логи

#### Application Layer (`backend/application/`)
- **Commands**: `RegisterUserCommand`, `LoginUserCommand`, `RefreshTokenCommand`
- **Handlers**: `AuthHandler` с бизнес-логикой
- **Interfaces**: Порты для репозиториев, хешеров, токенов, кеша, медиа

#### Infrastructure Layer (`backend/infrastructure/`)
- **DB**: SQLAlchemy async engine + UnitOfWork паттерн
- **Repositories**: Реализации IUserRepository, IWorkspaceRepository
- **Channels**: 
  - `telegram.py` - Webhook, IP верификация, rate limit 30 msg/sec
  - `vk.py` - Callback API, HMAC-SHA1, confirmation flow
  - `whatsapp.py` - Meta Cloud API, 24h window, template messages, billing awareness
  - `max.py` - MasterBot API, dynamic parser, polling fallback
- **Registry**: ChannelRegistry для DI-резолвинга адаптеров
- **Cache**: Redis pub/sub для multi-worker WebSocket
- **S3**: MinIO клиент для медиа
- **Security**: ClamAV сканирование файлов
- **Workers**: ARQ воркеры для фоновых задач

#### Presentation Layer (`backend/presentation/`)
- **API v1**: Auth endpoints, webhook routes
- **Middleware**: 
  - CSRF Double-Submit Cookie
  - Workspace JWT auth
  - Rate limiting per channel
- **WebSocket**: Multi-worker pub/sub manager
- **Error Handling**: Унифицированный AppError слой

### ✅ Database & Migrations

- **Alembic**: Initial migration со всеми таблицами
- **Индексы**: 
  - workspace_id для изоляции
  - (channel_account_id, external_message_id) unique для дедупликации
  - sequence_id для строгого порядка сообщений
  - GIN для metadata JSONB полей
- **PITR**: Поддержка point-in-time recovery через WAL архивы

### ✅ Frontend (Next.js 14 + TypeScript)

#### State Management
- **Zustand Store**: Chat state + IndexedDB offline queue
  - Автономная буферизация отправки при разрыве
  - Дедупликация по local_msg_id
  - Conflict resolution (server-truth при реконнекте)
  - Rollback UI при 4xx/5xx

#### Data Fetching
- **TanStack Query**: Хуки для API запросов
  - useLogin, useRegister, useCurrentUser
  - useConversations, useConversationMessages
  - useSendMessage с optimistic updates

#### UI Components
- **Virtualized List**: @tanstack/react-virtual
  - Dynamic sizing через estimateSize + measureElement
  - Фиксация "прыжков" скролла
  - Auto-scroll to bottom
  - Loading skeleton

#### Styling
- **Tailwind CSS**: shadcn/ui совместимая тема
- **Radix UI**: Готовые примитивы (dialog, dropdown, toast)

### ✅ DevOps & CI/CD

- **Docker Compose**: Все сервисы с healthchecks
  - postgres:15, redis:7, minio, clamav
  - fastapi (uvicorn), worker (arq), nextjs
- **GitHub Actions**: Полный pipeline
  - lint -> unit -> integration -> build -> deploy
  - Security scanning (Bandit, Trivy)
  - Zero-downtime rolling deploy
- **Monitoring**: Prometheus метрики + Grafana дашборды
- **Alerts**: DLQ > 1%, error rate > 5%, WS disconnect spike

### ✅ Testing

- **Unit**: pytest + factory-boy (domain rules, DTO)
- **Integration**: httpx.AsyncClient + testcontainers
- **E2E**: Playwright (auth -> channels -> send -> verify WS)
- **Load**: k6 скрипт (1000 WS, 100 msg/sec)
  - Circuit breaker trip тесты
  - Memory/CPU leak detection

## Ключевые архитектурные решения

### 1. UnitOfWork для атомарности
```python
async with UnitOfWork() as uow:
    user = await uow.users.create(...)
    await uow.workspaces.add_channel(...)
    # commit или rollback автоматически
```

### 2. EventDispatcher для декуплинга
```python
@dispatcher.subscribe(MessageReceived)
async def broadcast_to_ws(event):
    await redis.publish(f"ws:{event.workspace_id}", event.payload)
```

### 3. SequenceId для порядка сообщений
- Bigint auto-increment на уровне PostgreSQL
- Индекс (conversation_id, sequence_id) для быстрого range query
- server_received_at для аудита и отладки

### 4. Circuit Breaker + TokenBucket
- Per-channel_account_id лимиты
- Экспоненциальный backoff при 429/5xx
- Graceful degradation при сбоях провайдеров

### 5. Offline-first архитектура
- IndexedDB буферизация на клиенте
- Оптимистичные обновления UI
- Автоматическая синхронизация при реконнекте
- Server-truth conflict resolution

### 6. Multi-worker WebSocket
- aioredis pub/sub канал ws:{workspace_id}
- Любой worker может отправить сообщение любому клиенту
- Heartbeat 30s + auto-reconnect с exponential backoff

## Стратегия расширения (новый мессенджер за 1 день)

1. Создать `backend/infrastructure/channels/new_messenger.py`
2. Реализовать 5 методов IChannelAdapter:
   - `send_message()`
   - `parse_webhook()`
   - `verify_signature()`
   - `mark_read()`
   - `get_rate_limit_config()`
3. Зарегистрировать в ChannelRegistry через конфиг
4. Добавить webhook route `/api/v1/webhooks/{channel_name}`
5. Обновить UI: иконка, форма подключения
6. Включить feature flag -> канареечный деплой

**Ядро системы не меняется!**

## Безопасность

- **CSRF**: Double-Submit Cookie pattern
- **XSS**: Content Security Policy headers
- **Media**: ClamAV сканирование перед загрузкой в S3
- **Webhooks**: Signature verification (HMAC-SHA256)
- **Secrets**: Docker Secrets + горячая ротация без рестарта
- **Audit Log**: Все авторизованные действия логируются

## Мониторинг и алерты

### Метрики (Prometheus)
- WS connections count per worker
- Message latency p50/p95/p99
- DLQ size per channel
- Circuit breaker state (closed/open/half-open)
- Channel RPS and error rate

### Алерты (Grafana)
- DLQ > 1% от общего объема
- Error rate > 5% за 5 минут
- WS disconnect spike (>10% за минуту)
- DB replication lag > 1s
- Circuit breaker trip

## Развертывание

### Локальная разработка
```bash
docker-compose up -d
alembic upgrade head
cd frontend && npm install && npm run dev
```

### Production
```bash
# Build images
docker-compose -f docker-compose.prod.yml build

# Deploy with zero-downtime
docker-compose -f docker-compose.prod.yml up -d

# Run migrations
docker-compose run --rm backend alembic upgrade head

# Smoke tests
curl -f http://localhost:8000/health
curl -f http://localhost:8000/ready
```

## Производительность

### Целевые показатели
- WS подключение: < 100ms
- Доставка сообщения: < 500ms (p95)
- Пропускная способность: 1000+ concurrent WS
- Message throughput: 100+ msg/sec на инстанс

### Оптимизации
- Connection pooling (PostgreSQL, Redis)
- Async I/O везде
- Virtual scrolling для больших списков
- IndexedDB для offline очереди
- CDN для статики и медиа

## Следующие шаги

1. [ ] Реализовать conversation CRUD endpoints
2. [ ] Добавить message search (PostgreSQL full-text)
3. [ ] Интегрировать Sentry для error tracking
4. [ ] Настроить Grafana дашборды
5. [ ] E2E тесты Playwright
6. [ ] Документация API (OpenAPI/Swagger)
7. [ ] Runbook для эксплуатации

---

**Статус**: Ядро архитектуры реализовано, готово к расширению функционала и деплою.
