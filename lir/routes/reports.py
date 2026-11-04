"""Reporting routes."""

from flask import Blueprint

bp = Blueprint("reports", __name__)


@bp.route("/revenus")
def earnings():
    return "Revenus - à compléter"
