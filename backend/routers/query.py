"""Endpoints del motor de consultas: JSON y descarga CSV."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import sentry_sdk

from csv_export import query_result_to_csv
from services.query.models import QueryRequest
from services.query.runner import run_query

router = APIRouter(prefix="/api", tags=["consultas"])


def _tag_query_shape(req: QueryRequest) -> None:
    """Etiqueta la transacción de Sentry para comparar latencias por forma."""
    if req.group_by == "year":
        shape = "year"
    elif req.group_by == "answer":
        shape = "flat"
    else:
        shape = "pivot"
    sentry_sdk.set_tag("query.shape", shape)


@router.post("/query")
def query(req: QueryRequest):
    """Corre una consulta del motor. Ver `services.query.runner.run_query`."""
    _tag_query_shape(req)
    return run_query(req)


@router.post("/query/csv")
def export_csv(req: QueryRequest):
    """Igual que /api/query pero devuelve el resultado como descarga CSV."""
    _tag_query_shape(req)
    body = query_result_to_csv(run_query(req))
    filename = f"encuesta_p{req.question_id}.csv"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
