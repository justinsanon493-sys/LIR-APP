"""Public-facing routes."""

from flask import Blueprint

bp = Blueprint("public", __name__)


@bp.route("/")
def public_home():
    return "Accueil public - à compléter"
