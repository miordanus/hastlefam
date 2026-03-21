"""ask_service.py — Natural language query engine.

User sends a question in Russian → GPT generates a SELECT-only SQL query →
we execute it against the DB → GPT formats the answer.

Safety: only SELECT queries are allowed. No DDL, DML, or CTEs with writes.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_SCHEMA_DESCRIPTION = """\
Database schema (PostgreSQL, schema "hastlefam"):

Table: transactions
  - id UUID PK
  - household_id UUID (FK households.id)
  - direction TEXT — one of: 'expense', 'income', 'transfer', 'exchange'
  - amount NUMERIC(14,2) — always positive
  - currency TEXT — one of: 'RUB', 'USD', 'EUR', 'PLN', 'USDT', 'AMD'
  - occurred_at TIMESTAMPTZ — when it happened
  - merchant_raw TEXT — merchant/payee name
  - primary_tag TEXT — category tag (nullable), e.g. 'продукты', 'кафе', 'подписки'
  - extra_tags JSONB — additional tags (array)
  - source TEXT — 'telegram', 'manual', 'import'
  - parse_status TEXT — 'ok', 'needs_correction'
  Key indexes: (household_id, occurred_at)

Table: accounts
  - id UUID PK, household_id UUID, name TEXT, currency TEXT, is_active BOOL

Table: balance_snapshots
  - id UUID PK, account_id UUID, household_id UUID, actual_balance NUMERIC(14,2), created_at TIMESTAMPTZ

Table: planned_payments
  - id UUID PK, household_id UUID, title TEXT, amount NUMERIC(14,2), currency TEXT, due_date DATE, status TEXT ('planned'/'paid')

Table: fx_rates
  - date DATE, from_currency TEXT, to_currency TEXT, rate NUMERIC(18,6)

IMPORTANT RULES:
- The user's household_id is provided as a parameter :household_id — ALWAYS filter by it
- EXCHANGE and TRANSFER transactions should be EXCLUDED from spend/income analysis unless explicitly asked
- Default currency is RUB
- All tags and merchants are in Russian (lowercase)
- Use occurred_at for date filtering, not created_at
- Return amounts formatted with 2 decimal places
- Keep queries simple and efficient, use GROUP BY where appropriate
- LIMIT results to 50 rows max
"""

_SYSTEM_PROMPT = f"""\
Ты — SQL-помощник для семейного бюджета. Пользователь задаёт вопрос на русском, \
ты генерируешь PostgreSQL SELECT запрос для ответа.

{_SCHEMA_DESCRIPTION}

Ответь ТОЛЬКО SQL запросом, без объяснений. Запрос должен начинаться с SELECT.
Всегда фильтруй по household_id = :household_id.
Текущая дата: {{current_date}}.
"""

_ANSWER_SYSTEM_PROMPT = """\
Ты — финансовый помощник семьи. Получил результаты SQL запроса по базе транзакций.
Ответь пользователю на русском, кратко и по делу. Форматируй суммы с пробелами \
(1 000, не 1000). Используй эмодзи умеренно.
"""

_FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|"
    r"EXECUTE|CALL|DO|SET\s+|LISTEN|NOTIFY|VACUUM|REINDEX|CLUSTER)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str | None:
    """Return error message if SQL is not a safe SELECT, else None."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped.upper().startswith("SELECT"):
        return "Запрос должен начинаться с SELECT."
    if _FORBIDDEN_PATTERNS.search(stripped):
        return "Запрос содержит запрещённые операции."
    if stripped.count(";") > 0:
        return "Несколько запросов не поддерживаются."
    return None


async def ask(
    question: str,
    household_id: str,
    db: Session,
) -> str:
    """Process a natural language question about finances."""
    from app.infrastructure.config.settings import get_settings

    settings = get_settings()
    api_key = settings.openai_api_key
    model = getattr(settings, "openai_model", "gpt-4.1-mini")
    current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key)
    except Exception as exc:
        log.warning("ask_service: OpenAI init failed: %s", exc)
        return "⚠️ Сервис временно недоступен."

    # Step 1: Generate SQL
    system = _SYSTEM_PROMPT.replace("{current_date}", current_date)
    try:
        sql_response = await client.chat.completions.create(
            model=model,
            max_tokens=500,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
        )
        raw_sql = sql_response.choices[0].message.content or ""
    except Exception as exc:
        log.warning("ask_service: SQL generation failed: %s", exc)
        return "⚠️ Не удалось сформировать запрос. Попробуй переформулировать."

    # Extract SQL from markdown code blocks if present
    sql = raw_sql.strip()
    if sql.startswith("```"):
        lines = sql.split("\n")
        sql = "\n".join(l for l in lines if not l.startswith("```")).strip()

    # Step 2: Validate
    error = _validate_sql(sql)
    if error:
        log.warning("ask_service: unsafe SQL rejected: %s | %s", error, sql[:200])
        return f"⚠️ {error}\nПопробуй переформулировать вопрос."

    # Step 3: Execute
    try:
        result = db.execute(
            text(sql),
            {"household_id": household_id},
        )
        columns = list(result.keys())
        rows = result.fetchmany(50)
        if not rows:
            data_text = "Запрос вернул 0 строк."
        else:
            header = " | ".join(columns)
            data_lines = [header]
            for row in rows:
                data_lines.append(" | ".join(str(v) for v in row))
            data_text = "\n".join(data_lines)
    except Exception as exc:
        log.warning("ask_service: SQL execution failed: %s | query: %s", exc, sql[:200])
        return "⚠️ Ошибка при выполнении запроса. Попробуй переформулировать."

    # Step 4: Format answer
    try:
        answer_response = await client.chat.completions.create(
            model=model,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"Вопрос: {question}\n\nРезультат запроса:\n{data_text}"},
            ],
        )
        return answer_response.choices[0].message.content or data_text
    except Exception:
        # Fallback: return raw data
        return f"📊 Результат:\n\n{data_text}"
