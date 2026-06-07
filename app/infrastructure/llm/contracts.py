from typing import Any
from pydantic import BaseModel, Field


class ParseDraftInput(BaseModel):
    text: str
    household_id: str
    user_id: str


class ParsedItem(BaseModel):
    item_type: str = Field(description='task|note|blocker|idea|shopping_item|decision|expense|income')
    title: str
    owner_user_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    due_date: str | None = None
    confidence: float = Field(ge=0, le=1)


class ParseDraftOutput(BaseModel):
    items: list[ParsedItem]
    missing_fields: list[str] = []


class MeetingSummaryInput(BaseModel):
    meeting_type: str
    notes_text: str


class MeetingSummaryOutput(BaseModel):
    summary: str
    decisions: list[str]
    tasks: list[dict[str, Any]]
    next_check_in: str | None = None


class FinanceInsightInput(BaseModel):
    period_start: str
    period_end: str
    transactions: list[dict[str, Any]]


class FinanceInsightOutput(BaseModel):
    summary: str
    anomalies: list[str]
    recommendations: list[str]


class WeeklyDigestInput(BaseModel):
    sprint_summary: dict[str, Any]
    finance_summary: dict[str, Any]


class WeeklyDigestOutput(BaseModel):
    digest_text: str
    follow_up_recommendations: list[str]


# ─── FoodOps: multi-action grocery parse (spec §10) ──────────────────────────

class FoodActionItem(BaseModel):
    intent: str = Field(description='update_inventory|discard|add_to_shopping_list|mark_check_needed')
    product: str
    status: str | None = Field(default=None, description='in_stock|low|almost_out|out|check|spoil_risk')
    quantity: float | None = None
    unit: str | None = None
    location: str | None = Field(default=None, description='fridge|freezer|shelf|unknown')
    reason: str | None = Field(default=None, description='shopping-list reason, e.g. manual_request')
    category: str | None = None
    confidence: str = Field(default='medium', description='low|medium|high')


class FoodParseOutput(BaseModel):
    actions: list[FoodActionItem]
