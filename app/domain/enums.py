from enum import StrEnum


class TaskType(StrEnum):
    TASK = 'task'
    RECURRING_TASK = 'recurring_task'
    SHOPPING_ITEM = 'shopping_item'


class TaskStatus(StrEnum):
    BACKLOG = 'backlog'
    TODO = 'todo'
    IN_PROGRESS = 'in_progress'
    DONE = 'done'
    CANCELED = 'canceled'


class NoteType(StrEnum):
    NOTE = 'note'
    BLOCKER = 'blocker'
    IDEA = 'idea'


class MeetingType(StrEnum):
    SPRINT_PLANNING = 'sprint_planning'
    WEEKLY_REVIEW = 'weekly_review'
    FINANCE_REVIEW = 'finance_review'
    HOUSEHOLD_SYNC = 'household_sync'


class Currency(StrEnum):
    RUB = 'RUB'
    USD = 'USD'
    USDT = 'USDT'
    EUR = 'EUR'
    AMD = 'AMD'


class CategoryKind(StrEnum):
    EXPENSE = 'expense'
    INCOME = 'income'


class TransactionDirection(StrEnum):
    EXPENSE = 'expense'
    INCOME = 'income'
    TRANSFER = 'transfer'
    EXCHANGE = 'exchange'


class DraftType(StrEnum):
    PARSE = 'parse'
    MEETING_SUMMARY = 'meeting_summary'
    FINANCE_INSIGHT = 'finance_insight'
    WEEKLY_DIGEST = 'weekly_digest'


class DebtDirection(StrEnum):
    I_OWE = 'i_owe'      # ты должен
    THEY_OWE = 'they_owe'  # тебе должны


# ─── FoodOps Home ────────────────────────────────────────────────────────────
# Stored as plain String columns (forgiving, no PG enum types); these StrEnums
# are the source of truth for valid values at the application layer.

class FoodCategory(StrEnum):
    READY_FOOD = 'ready_food'
    DAIRY = 'dairy'
    PROTEIN = 'protein'
    MEAT = 'meat'
    FISH = 'fish'
    EGGS = 'eggs'
    VEGETABLES = 'vegetables'
    FRUITS = 'fruits'
    BREAD = 'bread'
    GRAINS = 'grains'
    PASTA = 'pasta'
    CANNED = 'canned'
    SAUCES = 'sauces'
    SPICES = 'spices'
    COFFEE_TEA = 'coffee_tea'
    FROZEN = 'frozen'
    SNACKS = 'snacks'
    HOUSEHOLD = 'household'
    UNKNOWN = 'unknown'


class InventoryStatus(StrEnum):
    IN_STOCK = 'in_stock'
    LOW = 'low'
    ALMOST_OUT = 'almost_out'
    OUT = 'out'
    CHECK = 'check'
    SPOIL_RISK = 'spoil_risk'


class ItemLocation(StrEnum):
    FRIDGE = 'fridge'
    FREEZER = 'freezer'
    SHELF = 'shelf'
    UNKNOWN = 'unknown'


class InventoryEventType(StrEnum):
    PURCHASE = 'purchase'
    MANUAL_COUNT = 'manual_count'
    CONSUMED = 'consumed'
    DISCARDED = 'discarded'
    ADDED_TO_LIST = 'added_to_list'
    REMOVED_FROM_LIST = 'removed_from_list'
    CORRECTION = 'correction'
    CHECK_NEEDED = 'check_needed'


class ShoppingReason(StrEnum):
    OUT_OF_STOCK = 'out_of_stock'
    ALMOST_OUT = 'almost_out'
    MIN_STOCK = 'min_stock'
    SPOIL_REPLACEMENT = 'spoil_replacement'
    BULK_PURCHASE = 'bulk_purchase'
    MANUAL_REQUEST = 'manual_request'
    UNKNOWN = 'unknown'


class ShoppingStatus(StrEnum):
    OPEN = 'open'
    BOUGHT = 'bought'
    DISMISSED = 'dismissed'


class ShoppingPriority(StrEnum):
    LOW = 'low'
    NORMAL = 'normal'
    HIGH = 'high'


class FoodIntent(StrEnum):
    UPDATE_INVENTORY = 'update_inventory'
    DISCARD = 'discard'
    ADD_TO_SHOPPING_LIST = 'add_to_shopping_list'
    MARK_CHECK_NEEDED = 'mark_check_needed'


class Confidence(StrEnum):
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'


class RawInputType(StrEnum):
    TEXT = 'text'
    VOICE_TRANSCRIPT = 'voice_transcript'
    RECEIPT_SCREENSHOT = 'receipt_screenshot'
    RECEIPT_TEXT = 'receipt_text'
    MANUAL = 'manual'


class ParsingStatus(StrEnum):
    PENDING = 'pending'
    PARSED = 'parsed'
    NEEDS_REVIEW = 'needs_review'
    FAILED = 'failed'
