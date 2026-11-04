"""Service request routes."""

from flask import Blueprint

bp = Blueprint("services", __name__)


@bp.route("/services")
def services_index():
    return "Services - à compléter"
