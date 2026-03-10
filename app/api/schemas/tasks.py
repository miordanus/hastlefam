from pydantic import BaseModel


class TaskSummaryOut(BaseModel):
    message: str
