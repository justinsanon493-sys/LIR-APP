"""Partner routes."""

from flask import Blueprint

bp = Blueprint("partners", __name__)


@bp.route("/partenaires")
def partners_index():
    return "Partenaires - à compléter"
