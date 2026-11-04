"""Customer routes."""

from flask import Blueprint

bp = Blueprint("customers", __name__)


@bp.route("/clients")
def customers_index():
    return "Clients - à compléter"
