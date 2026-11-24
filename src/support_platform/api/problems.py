"""Exception -> RFC 9457 problem+json mapping. Every error leaves the API through here."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from support_platform.domain.errors import ProblemError
from support_platform.observability.logging import correlation_id_var
from support_platform.services.customers import upstream_to_problem
from support_platform.upstreams.resilience import UpstreamError

log = logging.getLogger("support_platform.api")
PROBLEM_JSON = "application/problem+json"


def problem_response(request: Request, problem: ProblemError) -> JSONResponse:
    body = problem.to_body(instance=request.url.path, correlation_id=correlation_id_var.get())
    return JSONResponse(body, status_code=problem.status, headers=problem.headers, media_type=PROBLEM_JSON)


def _pointer(loc: tuple) -> str:
    where, *rest = loc
    if where == "body":
        return "/" + "/".join(str(p) for p in rest)
    return f"{where}/" + "/".join(str(p) for p in rest)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"pointer": _pointer(tuple(e["loc"])), "detail": e["msg"]} for e in exc.errors()]
        return problem_response(request, ProblemError(400, "validation-error", "Request validation failed",
                                                      "One or more fields are invalid.", errors=errs))

    @app.exception_handler(UpstreamError)
    async def _upstream(request: Request, exc: UpstreamError) -> JSONResponse:
        return problem_response(request, upstream_to_problem(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem_response(request, ProblemError(exc.status_code, slug, str(exc.detail), None,
                                                      headers=dict(exc.headers or {})))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return problem_response(request, ProblemError(500, "internal-error", "Internal server error",
                                                      "An unexpected error occurred. Quote the correlationId."))
