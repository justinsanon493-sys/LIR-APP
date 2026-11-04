"""Delivery management routes."""

from flask import Blueprint

bp = Blueprint("deliveries", __name__)


@bp.route("/livraisons")
def deliveries_index():
    return "Livraisons - à compléter"
