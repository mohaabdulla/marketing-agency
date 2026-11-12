from pydantic import Field
from fastapi.responses import Response
from .api import router, guard
from .schemas import Strict, Id
from . import privacy


@router.get('/clients/{client_id}/privacy/erasure-preview')
def erasure_preview(client_id: Id):
    return guard(privacy.preview, client_id)


@router.get('/clients/{client_id}/privacy/retention-review')
def retention_review(client_id: Id):
    return guard(privacy.retention_review, client_id)


@router.post('/clients/{client_id}/privacy/export')
def client_export(client_id: Id):
    return Response(guard(privacy.export_client, client_id), media_type='application/zip',
                    headers={'Content-Disposition': 'attachment; filename="client-data.zip"'})


class Erasure(Strict):
    expected_version: int = Field(ge=1)
    confirmation: str = Field(max_length=80)
    review_token: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/clients/{client_id}/privacy/erase')
def erase(client_id: Id, body: Erasure):
    return guard(privacy.erase, client_id, body.expected_version, body.confirmation, body.review_token)
