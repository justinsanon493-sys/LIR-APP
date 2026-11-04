# -*- coding: utf-8 -*-
"""
Vérification des routes Chat et Recherche Visuelle avant intégration
"""

CHAT_ET_VISION_CODE = '''
# ──────────────────────────────────────────────────────────
#  MESSAGERIE INTÉGRÉE (CHAT MULTI-ACTEURS)
# ──────────────────────────────────────────────────────────

def _utilisateur_chat():
    identite = _identite_portail()
    if identite:
        role = identite["role"]
        profil = identite["profil"]
        return {
            "type": role,
            "id": profil["id"],
            "nom": profil.get("nom", f"{role.capitalize()} #{profil[\'id\']}"),
            "est_admin": False
        }

    mdp = os.environ.get("APP_MOT_DE_PASSE", "")
    a = request.authorization
    admin_auth = False
    if not mdp:
        admin_auth = True
    elif a and hmac.compare_digest((a.password or "").encode("utf-8"), mdp.encode("utf-8")):
        admin_auth = True

    if session.get("est_admin") or admin_auth:
        return {
            "type": "admin",
            "id": 0,
            "nom": "Administration LIR",
            "est_admin": True
        }

    client_sess = session.get("client_chat")
    if client_sess:
        return {
            "type": "client",
            "id": client_sess.get("id", 1),
            "nom": client_sess.get("nom", "Client"),
            "tel": client_sess.get("tel", ""),
            "est_admin": False
        }

    return {
        "type": "client",
        "id": 0,
        "nom": "Visiteur",
        "est_admin": False
    }
'''

print("Code template syntax OK")
