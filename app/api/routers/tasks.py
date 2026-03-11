from fastapi import APIRouter

router = APIRouter(prefix='/tasks', tags=['tasks'])


@router.get('/summary')
def tasks_summary() -> dict:
    return {'message': 'Sprint/task summary placeholder'}
