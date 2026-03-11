from fastapi import APIRouter

router = APIRouter(prefix='/reviews', tags=['reviews'])


@router.post('/agenda/{meeting_type}')
def create_agenda(meeting_type: str) -> dict:
    return {'meeting_type': meeting_type, 'status': 'agenda_draft_placeholder'}
