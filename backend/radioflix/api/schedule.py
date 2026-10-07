from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from radioflix.schemas.reservations import RecordingError
from radioflix.api.recording_auth import recording_authorization


class GuideReservationRequest(BaseModel):
    date: Date
    schedule_revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    mode: Literal['once', 'weekly']


def schedule_router(service):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    router = APIRouter(prefix='/api', tags=['schedule'], dependencies=[Depends(no_cache), Depends(recording_authorization(service.reservations))])

    def call(function, *args):
        try:
            return function(*args)
        except RecordingError as e:
            raise HTTPException(422 if e.code in ('date_range', 'station') else 409,
                                detail={'code': e.code, 'message': e.message}) from None

    @router.get('/stations')
    def stations():
        return {'stations': call(service.adapter.stations)}

    @router.get('/schedule')
    def schedule(date: list[Date] = Query(...), station: str | None = None):
        return call(service.schedule, station, date)

    @router.post('/broadcasts/{broadcast_id}/reservations')
    def reserve(broadcast_id: str, request: GuideReservationRequest):
        return call(service.reserve, broadcast_id, request)

    return router
