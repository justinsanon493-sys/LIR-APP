"""Account routes."""

from flask import Blueprint

bp = Blueprint("accounts", __name__)


@bp.route("/login")
def login():
    return "Connexion - à compléter"
