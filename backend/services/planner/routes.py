from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse


class PlannerRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except (HTTPException, RequestValidationError):
                raise
            except Exception as error:
                from logger import log_event
                # Log operation/type, never OAuth responses or private event contents.
                log_event('ERROR', 'Planner', f'Помилка задачника: {request.method} {request.url.path}, {type(error).__name__}')
                return JSONResponse(status_code=503, content={'detail': 'Не вдалося виконати дію задачника. Дані збережені; спробуйте ще раз'})
        return handler
