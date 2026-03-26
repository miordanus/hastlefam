"""
month.py — /month command handler.
Shows MTD spend, income, planned, top tags, and unresolved items.
Supports: /month, /month 2, /month 2026-02, and prev/next navigation buttons.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.application.services.finance_service import FinanceService
from app.infrastructure.db.models import User
from app.infrastructure.db.session import SessionLocal

router = Router()

_MONTH_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}

_CUR_SYMBOL = {"RUB": "\u20bd", "USD": "$", "EUR": "\u20ac", "PLN": "z\u0142", "USDT": "\u20ae"}


def _cur_sym(currency: str) -> str:
    return _CUR_SYMBOL.get(currency, currency)


def _find_user(db, telegram_id: str):
    return db.query(User).filter(User.telegram_id == telegram_id, User.is_active.is_(True)).first()


def _fmt_amount(v: Decimal) -> str:
    """Format amount with space thousands separator."""
    return f"{v:,.0f}".replace(",", " ")


def _parse_month_arg(text: str) -> date | None:
    """Parse month argument from command text.

    Supports:
    - /month 2       -> February of current year
    - /month 02      -> February of current year
    - /month 2026-02 -> February 2026
    - /month 2026-2  -> February 2026
    """
    arg = text.replace("/month", "", 1).strip()
    if not arg:
        return None

    # YYYY-MM or YYYY-M
    m = re.match(r"^(\d{4})-(\d{1,2})$", arg)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None

    # Just a month number (1-12)
    m = re.match(r"^(\d{1,2})$", arg)
    if m:
        month_num = int(m.group(1))
        if 1 <= month_num <= 12:
            today = datetime.now(timezone.utc).date()
            return date(today.year, month_num, 1)

    return None


def _prev_month(d: date) -> date:
    if d.month == 1:
        return date(d.year - 1, 12, 1)
    return date(d.year, d.month - 1, 1)


def _next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


# ── ARCHIVED 2026-03-26 ─────────────────────────────────────────────────────
# Functions below were part of the old /month rendering (ASCII bars, MoM
# dynamics, grand-total RUB, balance section, debts block). Replaced by the
# CPO-mockup redesign. Kept here for reference; do NOT import or call.
#
# Archived imports (required by helpers below):
#   from app.application.services.fx_service import convert_to_rub
#   from app.domain.enums import DebtDirection
#   from app.infrastructure.db.models import Debt
#
# def _format_currency_block(by_currency: dict[str, Decimal]) -> str:
#     if not by_currency:
#         return "  0 \u20bd"
#     return "\n".join(f"  {_fmt_amount(v)} {_cur_sym(cur)}" for cur, v in by_currency.items())
#
# def _ascii_bar(value: Decimal, max_value: Decimal, width: int = 10) -> str:
#     """Return an ASCII bar like '████░░░░░░' proportional to value/max_value."""
#     if max_value <= 0:
#         return "░" * width
#     filled = int(round(float(value / max_value) * width))
#     filled = max(0, min(filled, width))
#     return "█" * filled + "░" * (width - filled)
#
# def _tag_list(tags: list, prev_tags: list, spend_total: Decimal) -> str:
#     """Build tag list with ASCII bars and MoM dynamics (Факт only: is_planned=False)."""
#     if not tags:
#         return ""
#     prev_map = {t["tag"]: t["amount"] for t in prev_tags}
#     max_amt = max((t["amount"] for t in tags[:5]), default=Decimal("0"))
#     lines = []
#     for t in tags[:5]:
#         tag = t["tag"]
#         amt = t["amount"]
#         bar = _ascii_bar(amt, max_amt)
#         prev_amt = prev_map.get(tag)
#         if prev_amt is None:
#             dyn = "  new"
#         elif prev_amt > 0:
#             change_pct = (amt - prev_amt) / prev_amt * 100
#             if change_pct >= 1:
#                 dyn = f"  ▲ +{change_pct:.0f}%"
#             elif change_pct <= -1:
#                 dyn = f"  ▼ {change_pct:.0f}%"
#             else:
#                 dyn = ""
#         else:
#             dyn = ""
#         lines.append(f"{tag}  {bar}  {_fmt_amount(amt)}{dyn}")
#     return "\n".join(lines)
#
# def _compute_grand_total_rub(by_currency: dict[str, Decimal], for_date: date, db) -> str | None:
#     """Return a formatted grand-total RUB string, or unavailable note."""
#     if not by_currency:
#         return None
#     if list(by_currency.keys()) == ["RUB"]:
#         return None
#     total = Decimal("0")
#     unavailable = False
#     for cur, amt in by_currency.items():
#         converted = convert_to_rub(amt, cur, for_date, db)
#         if converted is None:
#             unavailable = True
#         else:
#             total += converted
#     if unavailable:
#         return "\u2248 ~ \u20bd (\u043a\u0443\u0440\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d)"
#     return f"\u2248 {_fmt_amount(total)} \u20bd"
#
# def _format_planned_total(planned: list, for_date: date, db) -> str:
#     """Compute planned payments total as currency summary + RUB equivalent."""
#     if not planned:
#         return ""
#     by_cur: dict[str, Decimal] = {}
#     for x in planned:
#         cur = x["currency"]
#         by_cur[cur] = by_cur.get(cur, Decimal("0")) + Decimal(str(x["amount"]))
#     parts = [f"{_fmt_amount(amt)} {_cur_sym(cur)}" for cur, amt in by_cur.items()]
#     line = "  \u0418\u0442\u043e\u0433\u043e: " + ", ".join(parts)
#     if len(by_cur) > 1 or "RUB" not in by_cur:
#         total_rub = Decimal("0")
#         ok = True
#         for cur, amt in by_cur.items():
#             converted = convert_to_rub(amt, cur, for_date, db)
#             if converted is None:
#                 ok = False
#             else:
#                 total_rub += converted
#         if ok:
#             line += f" \u2248 {_fmt_amount(total_rub)} \u20bd"
#     return line
#
# def _build_debts_block(household_id: str, for_date: date, db) -> str:
#     """Build debts summary line: 'Долги: тебе должны +X / ты должен -Y'."""
#     try:
#         import uuid as _uuid
#         hid = _uuid.UUID(household_id)
#         open_debts = (
#             db.query(Debt)
#             .filter(Debt.household_id == hid, Debt.settled_at.is_(None))
#             .all()
#         )
#         if not open_debts:
#             return ""
#         they_owe_rub = Decimal("0")
#         i_owe_rub = Decimal("0")
#         for d in open_debts:
#             amount_rub = convert_to_rub(Decimal(str(d.amount)), d.currency, for_date, db)
#             if amount_rub is None:
#                 amount_rub = Decimal(str(d.amount))
#             if d.direction == DebtDirection.THEY_OWE:
#                 they_owe_rub += amount_rub
#             else:
#                 i_owe_rub += amount_rub
#         parts = []
#         if they_owe_rub > 0:
#             parts.append(f"тебе должны +{_fmt_amount(they_owe_rub)} ₽")
#         if i_owe_rub > 0:
#             parts.append(f"ты должен \u2212{_fmt_amount(i_owe_rub)} ₽")
#         if not parts:
#             return ""
#         return "💸 Долги: " + " / ".join(parts)
#     except Exception:
#         return ""
#
# def _render_balance_section(balance_summary: dict, for_date: date, db) -> str:
#     """Render balance net worth + per-account deltas for /month."""
#     accounts = balance_summary.get("accounts", [])
#     total_by_currency = balance_summary.get("total_by_currency", {})
#     if not accounts or not any(a["current_balance"] is not None for a in accounts):
#         return ""
#     lines = ["\U0001f4bc \u0411\u0430\u043b\u0430\u043d\u0441\u044b:"]
#     for a in accounts:
#         cur_bal = a["current_balance"]
#         if cur_bal is None:
#             continue
#         sym = _cur_sym(a["currency"])
#         delta = a["delta"]
#         delta_str = ""
#         if delta is not None and delta != 0:
#             sign = "+" if delta > 0 else "\u2212"
#             delta_str = f" ({sign}{_fmt_amount(abs(delta))})"
#         lines.append(f"  {a['name']}: {_fmt_amount(cur_bal)} {sym}{delta_str}")
#     if total_by_currency:
#         total_parts = [f"{_fmt_amount(amt)} {_cur_sym(cur)}" for cur, amt in total_by_currency.items()]
#         total_line = "  \u0418\u0442\u043e\u0433\u043e: " + ", ".join(total_parts)
#         if len(total_by_currency) > 1 or "RUB" not in total_by_currency:
#             total_rub = Decimal("0")
#             ok = True
#             for cur, amt in total_by_currency.items():
#                 converted = convert_to_rub(amt, cur, for_date, db)
#                 if converted is None:
#                     ok = False
#                 else:
#                     total_rub += converted
#             if ok:
#                 total_line += f" \u2248 {_fmt_amount(total_rub)} \u20bd"
#         lines.append(total_line)
#     return "\n".join(lines)
#
# def _render_month(  # OLD signature — replaced by new CPO-mockup version above
#     summary: dict, for_date: date,
#     grand_total_rub: str | None = None, prev_summary: dict | None = None,
#     balance_section: str = "", planned_totals: dict | None = None,
#     budget_pressure: int = 0, debts_block: str = "",
# ) -> tuple[str, InlineKeyboardMarkup]:
#     month_label = f"{_MONTH_RU[for_date.month]} {for_date.year}"
#     spend_block = _format_currency_block(summary["spend_by_currency"]) if summary["spend_by_currency"] else "  Расходов пока нет."
#     income_block = _format_currency_block(summary["income_by_currency"]) if summary["income_by_currency"] else "  Ничего за этот месяц."
#     if planned_totals:
#         plan_str = "  " + "  |  ".join(f"{_fmt_amount(a)} {_cur_sym(c)}" for c, a in planned_totals.items())
#     else:
#         planned = summary["upcoming_until_month_end"]
#         if planned:
#             by_cur: dict[str, Decimal] = {}
#             for x in planned:
#                 cur = x["currency"]
#                 by_cur[cur] = by_cur.get(cur, Decimal("0")) + Decimal(str(x["amount"]))
#             plan_str = "  " + "  |  ".join(f"{_fmt_amount(a)} {_cur_sym(c)}" for c, a in by_cur.items())
#         else:
#             plan_str = "  Ничего не запланировано."
#     tags = summary["top_tags"]
#     prev_tags = (prev_summary or {}).get("top_tags", [])
#     spend_total = sum(summary["spend_by_currency"].values(), Decimal("0"))
#     tags_block = _tag_list(tags, prev_tags, spend_total) if tags else "  Тегов пока нет."
#     untagged = summary.get("untagged_count", 0)
#     lines = [f"📊 <b>{month_label}</b>", "", f"<b>Факт:</b>\n{spend_block}"]
#     if grand_total_rub:
#         lines.append(f"  {grand_total_rub}")
#     lines += ["", f"Доходы:\n{income_block}", "", f"<b>План до конца месяца:</b>\n{plan_str}"]
#     if budget_pressure > 0:
#         lines.append(f"\n⚠️ {budget_pressure} {'категория под давлением' if budget_pressure == 1 else 'категории под давлением'}")
#     lines += ["", f"Топ теги (факт):\n{tags_block}"]
#     if balance_section:
#         lines += ["", balance_section]
#     if debts_block:
#         lines += ["", debts_block]
#     if untagged:
#         lines += ["", f"⚠️ {untagged} записей без тега — нажми кнопку ниже."]
#     keyboard = _build_month_keyboard(untagged, for_date)
#     return "\n".join(lines), keyboard
# ── END ARCHIVED ─────────────────────────────────────────────────────────────


def _build_month_keyboard(untagged_count: int, for_date: date) -> InlineKeyboardMarkup:
    from app.infrastructure.config.settings import get_settings
    settings = get_settings()

    rows: list[list[InlineKeyboardButton]] = []

    # Row 1: action buttons
    row1: list[InlineKeyboardButton] = []
    if settings.insights_enabled:
        row1.append(InlineKeyboardButton(
            text="💡 Инсайты",
            callback_data=f"month:insights:{for_date.isoformat()}",
        ))
    row1.append(InlineKeyboardButton(text="📊 Бюджеты", callback_data="month:open_budgets"))
    row1.append(InlineKeyboardButton(text="📅 План", callback_data="month:open_upcoming"))
    if untagged_count > 0:
        row1.append(InlineKeyboardButton(
            text=f"🏷 Разобрать ({untagged_count})",
            callback_data="month:open_inbox",
        ))
    rows.append(row1)

    # Row 2: navigation
    prev_d = _prev_month(for_date)
    next_d = _next_month(for_date)
    rows.append([
        InlineKeyboardButton(
            text=f"◀ {_MONTH_RU[prev_d.month]}",
            callback_data=f"month:nav:{prev_d.isoformat()}",
        ),
        InlineKeyboardButton(
            text=f"{_MONTH_RU[next_d.month]} ▶",
            callback_data=f"month:nav:{next_d.isoformat()}",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _fmt_multicur(by_cur: dict[str, Decimal]) -> str:
    """Format multi-currency amounts as '12 340 ₽ | 49 $'."""
    if not by_cur:
        return "0 \u20bd"
    return " | ".join(f"{_fmt_amount(v)} {_cur_sym(c)}" for c, v in by_cur.items())


def _render_month(
    summary: dict,
    for_date: date,
    planned_totals: dict | None = None,
    budget_statuses: list | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Render month summary text and keyboard per CPO mockup."""
    month_label = f"{_MONTH_RU[for_date.month]} {for_date.year}"
    spend_by_cur = summary["spend_by_currency"]
    income_by_cur = summary["income_by_currency"]
    untagged = summary.get("untagged_count", 0)

    # ── Остаток = income − spend per currency ─────────────────────────────
    all_curs = sorted(set(spend_by_cur) | set(income_by_cur))
    balance_by_cur: dict[str, Decimal] = {
        cur: income_by_cur.get(cur, Decimal("0")) - spend_by_cur.get(cur, Decimal("0"))
        for cur in all_curs
    }
    has_negative_balance = any(v < 0 for v in balance_by_cur.values())
    balance_parts = []
    for cur, val in balance_by_cur.items():
        prefix = "+" if val >= 0 else ""
        balance_parts.append(f"{prefix}{_fmt_amount(val)} {_cur_sym(cur)}")
    balance_str = " | ".join(balance_parts) if balance_parts else "0 \u20bd"
    balance_line = f"💰 Остаток: {balance_str}" + (" ⚠️" if has_negative_balance else "")

    # ── Расходы / Доходы ──────────────────────────────────────────────────
    spend_line = f"📤 Расходы: {_fmt_multicur(spend_by_cur)}"
    income_line = f"📥 Доходы: {_fmt_multicur(income_by_cur)}"

    # ── План до конца месяца ──────────────────────────────────────────────
    plan_lines: list[str] = []
    if planned_totals:
        plan_str = " | ".join(
            f"{_fmt_amount(v)} {_cur_sym(c)}" for c, v in planned_totals.items()
        )
        plan_line = f"📅 План до конца месяца: {plan_str}"
        # → после плана (only for currencies present in balance)
        after_parts = []
        after_negative = False
        for cur, plan_amt in planned_totals.items():
            bal = balance_by_cur.get(cur)
            if bal is not None:
                after = bal - plan_amt
                prefix = "+" if after >= 0 else ""
                after_parts.append(f"{prefix}{_fmt_amount(after)} {_cur_sym(cur)}")
                if after < 0:
                    after_negative = True
        if after_parts:
            after_str = " | ".join(after_parts)
            plan_line += f" → после плана останется: {after_str}" + (" ⚠️" if after_negative else "")
        plan_lines = [plan_line]

    # ── Бюджеты (топ риски) ───────────────────────────────────────────────
    budget_lines: list[str] = []
    if budget_statuses:
        over = [s for s in budget_statuses if s["status"] == "over_budget"]
        risk = [s for s in budget_statuses if s["status"] == "at_risk"]
        ok_first = next((s for s in budget_statuses if s["status"] == "ok"), None)
        risk_items = over + risk + ([ok_first] if ok_first else [])
        if risk_items:
            budget_lines.append("📊 Бюджеты (топ риски):")
            for s in risk_items:
                name = s["category_name"]
                sym = _cur_sym(s["currency"])
                if s["status"] == "over_budget":
                    overage = s["actual_spent"] - s["limit_amount"]
                    budget_lines.append(f"• {name} 🔴 перерасход {_fmt_amount(overage)} {sym}")
                elif s["status"] == "at_risk":
                    rem = s["remaining_after_planned"]
                    budget_lines.append(f"• {name} ⚠️ риск ({_fmt_amount(rem)} осталось)")
                else:
                    rem = s["remaining_after_planned"]
                    budget_lines.append(f"• {name} ✅ {_fmt_amount(rem)} осталось")

    # ── Топ теги (top-3, is_planned=False already filtered in month_summary) ─
    top_tags = summary["top_tags"][:3]
    tag_lines: list[str] = []
    if top_tags:
        tag_lines.append("🏷 Топ теги:")
        for t in top_tags:
            amt_str = _fmt_multicur(t["by_currency"])
            tag_lines.append(f"• {t['tag']} {amt_str}")

    # ── Assemble ──────────────────────────────────────────────────────────
    sep = "──────────────────"
    lines: list[str] = [f"<b>{month_label}</b>", ""]
    lines += [balance_line, spend_line, income_line]
    lines += plan_lines
    if budget_lines:
        lines += [sep] + budget_lines
    if tag_lines:
        lines += [sep] + tag_lines
    if untagged:
        lines += ["", f"Без тега: {untagged}"]

    keyboard = _build_month_keyboard(untagged, for_date)
    return "\n".join(lines), keyboard


def _fetch_and_render(db, user, for_date: date) -> tuple[str, InlineKeyboardMarkup]:
    """Shared logic: fetch summary, render month view."""
    svc = FinanceService(db)
    summary = svc.month_summary(str(user.household_id), for_date=for_date)
    planned_totals = svc.get_planned_total(str(user.household_id), for_date.year, for_date.month)

    budget_statuses: list = []
    try:
        from app.application.services.budget_service import get_budget_status
        month_key = for_date.strftime("%Y-%m")
        budget_statuses = get_budget_status(str(user.household_id), month_key, db) or []
    except Exception:
        pass

    return _render_month(
        summary,
        for_date,
        planned_totals=planned_totals or None,
        budget_statuses=budget_statuses,
    )


@router.message(Command("month"))
async def month_command(message: Message):
    with SessionLocal() as db:
        user = _find_user(db, str(message.from_user.id)) if message.from_user else None
        if not user:
            await message.answer(
                "\u26a0\ufe0f \u042f \u043d\u0435 \u0432\u0438\u0436\u0443 \u0442\u0432\u043e\u0439 \u043f\u0440\u043e\u0444\u0438\u043b\u044c \u0432 \u044d\u0442\u043e\u043c household.\n\n"
                "\u041d\u0443\u0436\u043d\u043e \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u0442\u044c Telegram-\u0430\u043a\u043a\u0430\u0443\u043d\u0442 \u043a \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044e HastleFam.\n"
                "\u0415\u0441\u043b\u0438 \u044d\u0442\u043e \u0442\u0432\u043e\u0439 \u0431\u043e\u0442 \u2014 \u043f\u0440\u043e\u0432\u0435\u0440\u044c \u043f\u0440\u0438\u0432\u044f\u0437\u043a\u0443 \u0432 \u0431\u0430\u0437\u0435."
            )
            return

        for_date = _parse_month_arg(message.text or "") or datetime.now(timezone.utc).date()
        text, keyboard = _fetch_and_render(db, user, for_date)

    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data and c.data.startswith("month:nav:"))
async def on_month_navigate(callback: CallbackQuery) -> None:
    await callback.answer()
    date_str = callback.data[len("month:nav:"):]
    try:
        for_date = date.fromisoformat(date_str)
    except ValueError:
        return

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            return
        text, keyboard = _fetch_and_render(db, user, for_date)

    # Telegram silently ignores edit_text if text is identical.
    # Append invisible marker to force update.
    text += f"\n\u200b"
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        # If edit fails (e.g. message not modified), send as new message
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "month:open_inbox")
async def on_month_inbox(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.inbox import send_inbox
    await send_inbox(callback.message, str(callback.from_user.id), edit=False)


@router.callback_query(lambda c: c.data == "month:open_budgets")
async def on_month_budgets(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.budgets import send_budgets
    await send_budgets(callback.message, str(callback.from_user.id))


@router.callback_query(lambda c: c.data == "month:open_upcoming")
async def on_month_upcoming(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.upcoming import send_upcoming
    await send_upcoming(callback.message, str(callback.from_user.id))


@router.callback_query(lambda c: c.data == "month:open_balances")
async def on_month_balances(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.balances import send_balances
    await send_balances(callback.message, str(callback.from_user.id))


@router.callback_query(lambda c: c.data and c.data.startswith("month:insights:"))
async def on_month_insights(callback: CallbackQuery) -> None:
    await callback.answer()
    date_str = callback.data[len("month:insights:"):]
    try:
        for_date = date.fromisoformat(date_str)
    except ValueError:
        return

    await callback.message.answer("\u23f3 \u0410\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u044e...")

    with SessionLocal() as db:
        user = _find_user(db, str(callback.from_user.id)) if callback.from_user else None
        if not user:
            await callback.message.answer("\u26a0\ufe0f \u041f\u0440\u043e\u0444\u0438\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
            return

        from app.application.services.insights_service import get_insights
        text = await get_insights(
            household_id=str(user.household_id),
            year=for_date.year,
            month=for_date.month,
            db=db,
        )

    await callback.message.answer(f"\U0001f4ca \u0418\u043d\u0441\u0430\u0439\u0442\u044b \u0437\u0430 {_MONTH_RU[for_date.month]} {for_date.year}:\n\n{text}")
