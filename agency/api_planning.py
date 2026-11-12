from fastapi.responses import Response
from .api import router, guard
from .schemas import Id
from .services import service
from .planning import paid_scenario, planning_bundle


@router.get('/clients/{client_id}/paid-plans/{plan_id}/scenario')
def scenario(client_id: Id, plan_id: Id):
    return guard(lambda: paid_scenario(service.get(client_id, plan_id, 'paid-plans')['data']))


@router.get('/clients/{client_id}/planning/{record_id}/export')
def export_plan(client_id: Id, record_id: Id):
    def run():
        item = service.get(client_id, record_id)
        if item['kind'] not in {'paid-plans', 'creators', 'creator-briefs', 'content-pillars', 'content-series'}:
            raise ValueError('Choose an organic, creator or paid-media plan')
        return planning_bundle(item)
    return Response(guard(run), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="draft-plan.zip"'})
