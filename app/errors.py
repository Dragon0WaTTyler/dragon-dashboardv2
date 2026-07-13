from __future__ import annotations

import logging

from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from app.api.v1.responses import error_response

logger = logging.getLogger(__name__)


def _is_api_request() -> bool:
    return request.path.startswith("/api/v1/")


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(CSRFError)
    def handle_csrf(error: CSRFError):
        if _is_api_request():
            return error_response("forbidden", "The security token is missing or invalid.", 400)
        return render_template("errors/error.html", status=400, title="Request expired"), 400

    @app.errorhandler(HTTPException)
    def handle_http(error: HTTPException):
        code = error.code or 500
        if _is_api_request():
            error_code = {
                400: "validation_error",
                401: "authentication_required",
                403: "forbidden",
                404: "not_found",
                409: "conflict",
            }.get(code, "internal_error")
            return error_response(error_code, error.description, code)
        return render_template("errors/error.html", status=code, title=error.name), code

    @app.errorhandler(Exception)
    def handle_unexpected(error: Exception):
        logger.exception("Unhandled application error", exc_info=error)
        if _is_api_request():
            return error_response("internal_error", "The request could not be completed.", 500)
        return render_template("errors/error.html", status=500, title="Something went wrong"), 500
