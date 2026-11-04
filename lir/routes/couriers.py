"""Courier routes."""

from flask import Blueprint

bp = Blueprint("couriers", __name__)


@bp.route("/portail-livreur")
def courier_portal():
    return "Portail livreur - à compléter"
