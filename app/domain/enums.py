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
