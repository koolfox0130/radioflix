from fastapi import APIRouter, Depends, HTTPException, Response

from radioflix.schemas.reservations import RecordingError, ReservationRequest


def reservation_router(service, programs):
    def no_cache(response: Response):
        response.headers["Cache-Control"] = "no-store"

    router = APIRouter(prefix="/api", tags=["reservations"], dependencies=[Depends(no_cache)])

    def public_error(error):
        return HTTPException(404 if error.code == "not_found" else 503 if error.uncertain else 409,
                             detail={"code": error.code, "message": error.message})

    def program_or_404(program_id):
        program = programs.find_program(program_id)
        if not program:
            raise HTTPException(404, detail={"message": "録音番組が見つかりません。"})
        return program

    @router.get("/programs/{program_id}/broadcasts")
    def broadcasts(program_id: str):
        program = program_or_404(program_id)
        try:
            items = service.adapter.broadcasts(program)
            return {"broadcasts": items, "message": "" if items else
                    "一致する次回放送が見つかりません。番組名・地域設定や放送予定を確認してください。"}
        except RecordingError as error:
            raise public_error(error) from None

    @router.get("/reservations")
    def listing():
        return service.list()

    @router.post("/reservations")
    def create(request: ReservationRequest):
        program = program_or_404(request.program_id)
        try:
            # Client cannot supply arbitrary station/times or native data.
            options = service.adapter.broadcasts(program)
            broadcast = next((item for item in options if item.id == request.broadcast_id), None)
            if broadcast is None:
                raise RecordingError("schedule_changed", "放送予定が変更されたか、受付時刻を過ぎています。番組詳細を開き直してください。")
            return service.create(program, broadcast, request.mode)
        except RecordingError as error:
            raise public_error(error) from None

    @router.delete("/reservations/{reservation_id}")
    def cancel(reservation_id: str):
        try:
            return service.cancel(reservation_id)
        except RecordingError as error:
            raise public_error(error) from None

    @router.post("/reservations/{reservation_id}/refresh")
    def refresh(reservation_id: str):
        if not any(item["id"] == reservation_id for item in service.list()):
            raise HTTPException(404, detail={"message": "予約が見つかりません。"})
        return service.reconcile(reservation_id)

    @router.post("/reservations/{reservation_id}/retry")
    def retry(reservation_id: str):
        if not any(item["id"] == reservation_id for item in service.list()):
            raise HTTPException(404, detail={"message": "予約が見つかりません。"})
        return service.reconcile(reservation_id, retry=True)

    return router
