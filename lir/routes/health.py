"""Health routes."""

from flask import Blueprint

bp = Blueprint("health", __name__)


@bp.route("/healthz")
def healthz():
    return {"ok": True, "service": "LIR"}
