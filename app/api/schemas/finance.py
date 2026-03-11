from pydantic import BaseModel


class FinanceSnapshotOut(BaseModel):
    message: str
