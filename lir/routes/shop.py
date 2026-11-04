"""Public shop routes."""

from flask import Blueprint

bp = Blueprint("shop", __name__)


@bp.route("/boutique")
def boutique():
    return "Boutique - à compléter"
