"""
month.py — /month command handler.
Shows MTD spend, income, planned, top tags, balances, and unresolved items.
Untagged items are shown separately and linked to /inbox via inline button.
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
from app.application.services.fx_service import convert_to_rub
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


def _format_currency_block(by_currency: dict[str, Decimal]) -> str:
    if not by_currency:
        return "  0 \u20bd"
    return "\n".join(f"  {_fmt_amount(v)} {_cur_sym(cur)}" for cur, v in by_currency.items())


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


def _build_month_keyboard(untagged_count: int, for_date: date) -> InlineKeyboardMarkup:
    rows = []

    # Navigation: < prev month | > next month
    prev_d = _prev_month(for_date)
    next_d = _next_month(for_date)
    rows.append([
        InlineKeyboardButton(
            text=f"\u25c0 {_MONTH_RU[prev_d.month][:3]}",
            callback_data=f"month:nav:{prev_d.isoformat()}",
        ),
        InlineKeyboardButton(
            text=f"{_MONTH_RU[next_d.month][:3]} \u25b6",
            callback_data=f"month:nav:{next_d.isoformat()}",
        ),
    ])

    if untagged_count > 0:
        rows.append([InlineKeyboardButton(
            text=f"\U0001f3f7 \u0420\u0430\u0437\u043e\u0431\u0440\u0430\u0442\u044c \u0431\u0435\u0437 \u0442\u0435\u0433\u0430 ({untagged_count})",
            callback_data="month:open_inbox",
        )])
    rows.append([
        InlineKeyboardButton(text="\U0001f5d3 \u041f\u043b\u0430\u043d\u044b", callback_data="month:open_upcoming"),
        InlineKeyboardButton(text="\U0001f4bc \u0411\u0430\u043b\u0430\u043d\u0441\u044b", callback_data="month:open_balances"),
    ])
    rows.append([
        InlineKeyboardButton(
            text="\U0001f4ca \u0418\u043d\u0441\u0430\u0439\u0442\u044b",
            callback_data=f"month:insights:{for_date.isoformat()}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _tag_list(tags: list, prev_tags: list, spend_total: Decimal) -> str:
    """Build tag list with percentages and MoM dynamics."""
    if not tags:
        return ""
    prev_map = {t["tag"]: t["amount"] for t in prev_tags}
    lines = []
    for t in tags[:5]:
        tag = t["tag"]
        amt = t["amount"]
        # Percentage of total spend
        pct = (amt / spend_total * 100) if spend_total else Decimal("0")
        amt_str = _fmt_amount(amt)
        # Dynamics vs previous month
        prev_amt = prev_map.get(tag)
        if prev_amt is None:
            dyn = " (new)"
        elif prev_amt > 0:
            change_pct = (amt - prev_amt) / prev_amt * 100
            if change_pct >= 1:
                dyn = f" (\u25b2 +{change_pct:.0f}%)"
            elif change_pct <= -1:
                dyn = f" (\u25bc {change_pct:.0f}%)"
            else:
                dyn = ""
        else:
            dyn = ""
        lines.append(f"#{tag} \u00b7 {pct:.0f}% \u00b7 {amt_str} \u20bd{dyn}")
    return "\n".join(lines)


def _compute_grand_total_rub(
    by_currency: dict[str, Decimal],
    for_date: date,
    db,
) -> str | None:
    """Return a formatted grand-total RUB string, or unavailable note."""
    if not by_currency:
        return None
    # If only RUB, no need for conversion line
    if list(by_currency.keys()) == ["RUB"]:
        return None
    total = Decimal("0")
    unavailable = False
    for cur, amt in by_currency.items():
        converted = convert_to_rub(amt, cur, for_date, db)
        if converted is None:
            unavailable = True
        else:
            total += converted
    if unavailable:
        return "\u2248 ~ \u20bd (\u043a\u0443\u0440\u0441 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d)"
    return f"\u2248 {_fmt_amount(total)} \u20bd"


def _format_planned_total(planned: list, for_date: date, db) -> str:
    """Compute planned payments total as currency summary + RUB equivalent."""
    if not planned:
        return ""
    by_cur: dict[str, Decimal] = {}
    for x in planned:
        cur = x["currency"]
        by_cur[cur] = by_cur.get(cur, Decimal("0")) + Decimal(str(x["amount"]))

    parts = [f"{_fmt_amount(amt)} {_cur_sym(cur)}" for cur, amt in by_cur.items()]
    line = "  \u0418\u0442\u043e\u0433\u043e: " + ", ".join(parts)

    # Add RUB equivalent if multi-currency
    if len(by_cur) > 1 or "RUB" not in by_cur:
        total_rub = Decimal("0")
        ok = True
        for cur, amt in by_cur.items():
            converted = convert_to_rub(amt, cur, for_date, db)
            if converted is None:
                ok = False
            else:
                total_rub += converted
        if ok:
            line += f" \u2248 {_fmt_amount(total_rub)} \u20bd"

    return line


def _render_balance_section(balance_summary: dict, for_date: date, db) -> str:
    """Render balance net worth + per-account deltas for /month."""
    accounts = balance_summary.get("accounts", [])
    total_by_currency = balance_summary.get("total_by_currency", {})

    if not accounts or not any(a["current_balance"] is not None for a in accounts):
        return ""

    lines = ["\U0001f4bc \u0411\u0430\u043b\u0430\u043d\u0441\u044b:"]

    # Per-account lines with delta
    for a in accounts:
        cur_bal = a["current_balance"]
        if cur_bal is None:
            continue
        sym = _cur_sym(a["currency"])
        delta = a["delta"]
        delta_str = ""
        if delta is not None and delta != 0:
            sign = "+" if delta > 0 else "\u2212"
            delta_str = f" ({sign}{_fmt_amount(abs(delta))})"
        lines.append(f"  {a['name']}: {_fmt_amount(cur_bal)} {sym}{delta_str}")

    # Grand total in RUB
    if total_by_currency:
        total_parts = [f"{_fmt_amount(amt)} {_cur_sym(cur)}" for cur, amt in total_by_currency.items()]
        total_line = "  \u0418\u0442\u043e\u0433\u043e: " + ", ".join(total_parts)

        if len(total_by_currency) > 1 or "RUB" not in total_by_currency:
            total_rub = Decimal("0")
            ok = True
            for cur, amt in total_by_currency.items():
                converted = convert_to_rub(amt, cur, for_date, db)
                if converted is None:
                    ok = False
                else:
                    total_rub += converted
            if ok:
                total_line += f" \u2248 {_fmt_amount(total_rub)} \u20bd"
        lines.append(total_line)

    return "\n".join(lines)


def _render_month(
    summary: dict,
    for_date: date,
    grand_total_rub: str | None = None,
    prev_summary: dict | None = None,
    balance_section: str = "",
) -> tuple[str, InlineKeyboardMarkup]:
    """Render month summary text and keyboard."""
    month_label = f"{_MONTH_RU[for_date.month]} {for_date.year}"

    if summary["spend_by_currency"]:
        spend_block = _format_currency_block(summary["spend_by_currency"])
    else:
        spend_block = "  \u0420\u0430\u0441\u0445\u043e\u0434\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442."

    if summary["income_by_currency"]:
        income_block = _format_currency_block(summary["income_by_currency"])
    else:
        income_block = "  \u041d\u0438\u0447\u0435\u0433\u043e \u0437\u0430 \u044d\u0442\u043e\u0442 \u043c\u0435\u0441\u044f\u0446."

    # Planned till month end
    planned = summary["upcoming_until_month_end"]
    if planned:
        planned_block = "\n".join(
            f"  {x['due_date']} \u00b7 {x['title']} \u00b7 {_fmt_amount(Decimal(str(x['amount'])))} {_cur_sym(x['currency'])}"
            for x in planned[:5]
        )
    else:
        planned_block = "  \u041d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u0437\u0430\u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043e."

    # Top tags — percentage + amount
    tags = summary["top_tags"]
    prev_tags = (prev_summary or {}).get("top_tags", [])
    spend_total = sum(summary["spend_by_currency"].values(), Decimal("0"))
    if tags:
        tags_block = _tag_list(tags, prev_tags, spend_total)
    else:
        tags_block = "  \u0422\u0435\u0433\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442."

    untagged = summary.get("untagged_count", 0)

    lines = [
        f"\U0001f4ca {month_label}",
        "",
        f"\U0001f4b8 \u041f\u043e\u0442\u0440\u0430\u0447\u0435\u043d\u043e:\n{spend_block}",
    ]
    if grand_total_rub:
        lines.append(f"  {grand_total_rub}")
    lines += [
        "",
        f"\U0001f4b0 \u041f\u0440\u0438\u0448\u043b\u043e:\n{income_block}",
        "",
        f"\U0001f5d3 \u0414\u043e \u043a\u043e\u043d\u0446\u0430 \u043c\u0435\u0441\u044f\u0446\u0430:\n{planned_block}",
    ]

    # Planned total line
    if planned:
        planned_total = summary.get("_planned_total_line", "")
        if planned_total:
            lines.append(planned_total)

    lines += [
        "",
        f"\U0001f3f7 \u041f\u043e \u0442\u0435\u0433\u0430\u043c:\n{tags_block}",
    ]

    if balance_section:
        lines += ["", balance_section]

    if untagged:
        lines += ["", f"\u26a0\ufe0f {untagged} \u0437\u0430\u043f\u0438\u0441\u0435\u0439 \u0431\u0435\u0437 \u0442\u0435\u0433\u0430 \u2014 \u043d\u0430\u0436\u043c\u0438 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435."]

    keyboard = _build_month_keyboard(untagged, for_date)
    return "\n".join(lines), keyboard


def _fetch_and_render(db, user, for_date: date) -> tuple[str, InlineKeyboardMarkup]:
    """Shared logic: fetch summary + balance, render month view."""
    svc = FinanceService(db)
    summary = svc.month_summary(str(user.household_id), for_date=for_date)
    prev_summary = svc.month_summary(str(user.household_id), for_date=_prev_month(for_date))
    grand_total_rub = _compute_grand_total_rub(summary["spend_by_currency"], for_date, db)

    # Planned total line
    planned = summary["upcoming_until_month_end"]
    planned_total = _format_planned_total(planned, for_date, db) if planned else ""
    summary["_planned_total_line"] = planned_total

    # Balance section
    balance_data = svc.balance_summary(str(user.household_id), for_date=for_date)
    balance_section = _render_balance_section(balance_data, for_date, db)

    return _render_month(summary, for_date, grand_total_rub, prev_summary, balance_section)


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

    await message.answer(text, reply_markup=keyboard)


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
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        # If edit fails (e.g. message not modified), send as new message
        await callback.message.answer(text, reply_markup=keyboard)


@router.callback_query(lambda c: c.data == "month:open_inbox")
async def on_month_inbox(callback: CallbackQuery) -> None:
    await callback.answer()
    from app.bot.handlers.inbox import send_inbox
    await send_inbox(callback.message, str(callback.from_user.id), edit=False)


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
