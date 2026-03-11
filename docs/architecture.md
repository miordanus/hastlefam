# Architecture Overview

- Presentation: FastAPI routes + aiogram handlers + HTML dashboard page.
- Application: service layer for tasks, meetings, finance, llm.
- Domain: enums and core rules.
- Infrastructure: SQLAlchemy models/session, Alembic, OpenAI provider, logging.
- Observability: structured logs, prompt logs, event log table.

Tradeoff: MVP keeps logic simple and synchronous where possible; background queue can be added in Sprint 1 with Redis for reminder jobs.
