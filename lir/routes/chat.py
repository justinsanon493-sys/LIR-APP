"""Chat routes."""

from flask import Blueprint

bp = Blueprint("chat", __name__)


@bp.route("/chat")
def chat_index():
    return "Chat - à compléter"
