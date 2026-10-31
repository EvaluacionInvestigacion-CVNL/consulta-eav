"""Contrato de entrada del motor de consultas."""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question_id: str
    filters: list[dict] = []
    group_by: str = "answer"
    initial_only: bool = True
    wave_id: str | None = None
    numeric_group_bins: list[float] | None = None
