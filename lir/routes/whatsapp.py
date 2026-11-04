"""WhatsApp routes."""

from flask import Blueprint

bp = Blueprint("whatsapp", __name__)


@bp.route("/whatsapp")
def whatsapp_index():
    return "WhatsApp - à compléter"
