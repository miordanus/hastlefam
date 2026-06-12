PROMPT_CONTRACTS = {
    'parse': {
        'purpose': 'Parse free text into structured draft items without inventing facts.',
        'failure_behavior': 'Return validation error; never mutate business tables.',
    },
    'meeting_summary': {
        'purpose': 'Summarize meeting notes and extract decisions/tasks drafts.',
        'failure_behavior': 'Store invalid draft and ask user to edit manually.',
    },
    'finance_insight': {
        'purpose': 'Explain finance trends from provided transaction set only.',
        'failure_behavior': 'No insight persisted if schema invalid.',
    },
    'weekly_digest': {
        'purpose': 'Generate weekly digest draft from structured sprint+finance inputs.',
        'failure_behavior': 'Fallback to static digest template.',
    },
    'food_parse': {
        'purpose': 'Split one free-text grocery message into multiple structured inventory/shopping actions without inventing products.',
        'failure_behavior': 'Return validation error; leave raw_input as needs_review and ask user to rephrase.',
    },
}
