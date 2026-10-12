from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from radioflix.api.recording_auth import recording_authorization
from radioflix.schemas.reservations import RecordingError


class TimefreeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    broadcast_episode_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    schedule_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    date: date


def timefree_router(service):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'
    router = APIRouter(prefix='/api/timefree', dependencies=[Depends(recording_authorization(service)), Depends(no_cache)])

    def call(fn, *args):
        try:
            return fn(*args)
        except RecordingError as e:
            raise HTTPException(404 if e.code == 'not_found' else 410 if e.code == 'expired' else 409,
                                detail={'code': e.code, 'message': e.message}) from None

    @router.post('/jobs', status_code=202)
    def create(request: TimefreeRequest):
        return call(service.create, request)

    @router.get('/jobs')
    def listing():
        return service.list()

    @router.get('/jobs/{job_id}')
    def get(job_id: str):
        return call(service.get, job_id)

    @router.delete('/jobs/{job_id}')
    def cancel(job_id: str):
        return call(service.cancel, job_id)

    return router
