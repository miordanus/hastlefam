from fastapi import APIRouter

router = APIRouter(prefix='/finance', tags=['finance'])


@router.get('/snapshot')
def finance_snapshot() -> dict:
    return {'message': 'Monthly finance snapshot placeholder'}
