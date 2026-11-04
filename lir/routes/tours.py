"""Route and itinerary routes."""

from flask import Blueprint

bp = Blueprint("tours", __name__)


@bp.route("/itineraire")
def itinerary():
    return "Itinéraire - à compléter"
