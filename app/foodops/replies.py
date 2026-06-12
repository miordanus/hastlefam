"""
replies.py — pure RU text formatting for the FoodOps bot.

No DB writes; takes already-loaded data and returns strings. Mirrors the spec
example responses (§24 confirmation, §25 "что купить?").
"""
from __future__ import annotations

from app.domain.enums import FoodCategory, InventoryStatus, ShoppingPriority, ShoppingReason
from app.foodops.services import spoilage_service
from app.foodops.services.inventory_service import ApplyResult, UpdatedItem
from app.infrastructure.db.models import FoodProduct, ShoppingListItem

PARSE_FAILED = (
    "Хм, не разобрал 🤔 Попробуй переформулировать — например: "
    "«молоко почти закончилось, добавь кофе в список»."
)

NOTHING_PARSED = "Понял, но не нашёл конкретных продуктов для обновления."

EMPTY_LIST = "Список покупок пуст 🎉"

NO_SPOILAGE_RISK = "Пока ничего критичного — риска порчи не вижу 👍"

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

_CATEGORY_RU = {
    FoodCategory.READY_FOOD.value: "готовая еда",
    FoodCategory.DAIRY.value: "молочка",
    FoodCategory.PROTEIN.value: "белок",
    FoodCategory.MEAT.value: "мясо",
    FoodCategory.FISH.value: "рыба",
    FoodCategory.EGGS.value: "яйца",
    FoodCategory.VEGETABLES.value: "овощи",
    FoodCategory.FRUITS.value: "фрукты",
    FoodCategory.BREAD.value: "хлеб",
    FoodCategory.GRAINS.value: "крупы",
    FoodCategory.PASTA.value: "паста",
    FoodCategory.CANNED.value: "консервы",
    FoodCategory.SAUCES.value: "соусы",
    FoodCategory.SPICES.value: "специи",
    FoodCategory.COFFEE_TEA.value: "кофе/чай",
    FoodCategory.FROZEN.value: "заморозка",
    FoodCategory.SNACKS.value: "снеки",
    FoodCategory.HOUSEHOLD.value: "бытовое",
    FoodCategory.UNKNOWN.value: "прочее",
}


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

    baseline = [i for i in items if i.reason == ShoppingReason.MIN_STOCK.value]
    others = [i for i in items if i.reason != ShoppingReason.MIN_STOCK.value]
    urgent = [i for i in others if i.priority == ShoppingPriority.HIGH.value]
    rest = [i for i in others if i.priority != ShoppingPriority.HIGH.value]

    lines = ["Сейчас купить:"]
    if urgent:
        lines.append("\nСрочно:")
        for i in urgent:
            hint = _REASON_RU.get(i.reason or "")
            name = _shop_name(db, i)
            lines.append(f"- {name} — {hint}" if hint else f"- {name}")
    if baseline:
        lines.append("\nБаза (держим всегда дома):")
        for i in baseline:
            lines.append(f"- {_shop_name(db, i)}")
    if rest:
        lines.append("\nЕщё:")
        for i in rest:
            lines.append(f"- {_shop_name(db, i)}")
    return "\n".join(lines)


def format_spoilage(rows) -> str:
    if not rows:
        return NO_SPOILAGE_RISK
    spoil = [r for r in rows if r.level == spoilage_service.SPOIL_RISK]
    warn = [r for r in rows if r.level == spoilage_service.WARN]
    lines = ["Риск порчи:"]
    if spoil:
        lines.append("\nСрочно (съесть или выкинуть):")
        lines += [f"- {r.name}" for r in spoil]
    if warn:
        lines.append("\nСкоро надо съесть:")
        lines += [f"- {r.name}" for r in warn]
    return "\n".join(lines)


def format_waste(summary) -> str:
    if summary.total == 0:
        return f"За {summary.window_days} дней ничего не выкидывали 👍"

    lines = [f"Отходы за {summary.window_days} дней: {summary.total} выкинуто."]

    if summary.by_category:
        lines.append("\nПо категориям:")
        lines += [f"- {_CATEGORY_RU.get(cat, cat)} — {n}" for cat, n in summary.by_category]

    if summary.by_product:
        lines.append("\nЧаще всего:")
        lines += [f"- {name} ({n})" for name, n in summary.by_product[:5]]

    if summary.repeated:
        lines.append("\nПовторяется (стоит покупать реже или меньше):")
        lines += [f"- {name} — {n} раза" for name, n in summary.repeated]

    lines.append("\nСтоимость пока не считаем (нет цен), но повтор фиксируем.")
    return "\n".join(lines)
