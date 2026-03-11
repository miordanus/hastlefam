from pydantic import ValidationError
from app.infrastructure.llm import contracts


CONTRACTS = {
    'parse': contracts.ParseDraftOutput,
    'meeting_summary': contracts.MeetingSummaryOutput,
    'finance_insight': contracts.FinanceInsightOutput,
    'weekly_digest': contracts.WeeklyDigestOutput,
}


def validate_contract_output(contract_name: str, payload: dict):
    model = CONTRACTS[contract_name]
    try:
        return model.model_validate(payload), None
    except ValidationError as exc:
        return None, str(exc)
