"""
replies.py — pure RU text formatting for the FoodOps bot.

No DB writes; takes already-loaded data and returns strings. Mirrors the spec
example responses (§24 confirmation, §25 "что купить?").
"""
from __future__ import annotations

from app.domain.enums import InventoryStatus, ShoppingPriority, ShoppingReason
from app.foodops.services.inventory_service import ApplyResult, UpdatedItem
from app.infrastructure.db.models import FoodProduct, ShoppingListItem

PARSE_FAILED = (
    "Хм, не разобрал 🤔 Попробуй переформулировать — например: "
    "«молоко почти закончилось, добавь кофе в список»."
)

NOTHING_PARSED = "Понял, но не нашёл конкретных продуктов для обновления."

EMPTY_LIST = "Список покупок пуст 🎉"

_STATUS_RU = {
    InventoryStatus.IN_STOCK.value: "есть",
    InventoryStatus.LOW.value: "мало",
    InventoryStatus.ALMOST_OUT.value: "почти закончилось",
    InventoryStatus.OUT.value: "закончилось",
    InventoryStatus.CHECK.value: "надо проверить",
    InventoryStatus.SPOIL_RISK.value: "риск порчи",
}

_REASON_RU = {
    ShoppingReason.OUT_OF_STOCK.value: "закончился",
    ShoppingReason.ALMOST_OUT.value: "почти закончился",
}

_UNIT_RU = {"pcs": "шт", "шт": "шт"}


def _fmt_qty(item: UpdatedItem) -> str:
    if item.quantity is not None:
        unit = _UNIT_RU.get(item.unit or "", item.unit or "")
        qty = f"{item.quantity:f}".rstrip("0").rstrip(".") if "." in str(item.quantity) else str(item.quantity)
        return f"{item.name} — {qty} {unit}".strip()
    return f"{item.name} — {_STATUS_RU.get(item.status, item.status)}"


def format_apply(result: ApplyResult) -> str:
    if result.total == 0:
        return NOTHING_PARSED

    lines = ["Ок, обновил."]

    if result.updated:
        lines.append("\nОстатки:")
        lines += [f"- {_fmt_qty(u)}" for u in result.updated]

    if result.discarded:
        lines.append("\nСписал:")
        lines += [f"- {name} — выкинуто" for name in result.discarded]

    if result.added_to_list:
        lines.append("\nДобавил в список:")
        seen = set()
        for name, _reason in result.added_to_list:
            if name not in seen:
                seen.add(name)
                lines.append(f"- {name}")

    if result.check_needed:
        lines.append("\nНадо проверить:")
        lines += [f"- {name}" for name in result.check_needed]

    return "\n".join(lines)


def _shop_name(db, item: ShoppingListItem) -> str:
    if item.product_id:
        product = db.get(FoodProduct, item.product_id)
        if product:
            return product.canonical_name
    return item.raw_product_name or "?"


def format_to_buy(db, items: list[ShoppingListItem]) -> str:
    if not items:
        return EMPTY_LIST

    urgent = [i for i in items if i.priority == ShoppingPriority.HIGH.value]
    rest = [i for i in items if i.priority != ShoppingPriority.HIGH.value]

    lines = ["Сейчас купить:"]
    if urgent:
        lines.append("\nСрочно:")
        for i in urgent:
            hint = _REASON_RU.get(i.reason or "")
            name = _shop_name(db, i)
            lines.append(f"- {name} — {hint}" if hint else f"- {name}")
    if rest:
        lines.append("\nЕщё:")
        for i in rest:
            lines.append(f"- {_shop_name(db, i)}")
    return "\n".join(lines)
