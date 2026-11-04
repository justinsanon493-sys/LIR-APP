# -*- coding: utf-8 -*-
"""
Module de messagerie intégrée (Chat) — LIR Livraisons Express
Permet aux clients, partenaires, livreurs et admins de communiquer.
"""

import sqlite3
import datetime


# ──────────────────────────────────────────────────────────
#  Initialisation des tables
# ──────────────────────────────────────────────────────────

def initialiser_tables_chat(con):
    """Crée les tables conversations et messages_chat si elles n'existent pas."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            type         TEXT NOT NULL DEFAULT 'general',
            participant_1_type TEXT NOT NULL,
            participant_1_id   INTEGER NOT NULL,
            participant_1_nom  TEXT NOT NULL DEFAULT '',
            participant_2_type TEXT NOT NULL,
            participant_2_id   INTEGER NOT NULL,
            participant_2_nom  TEXT NOT NULL DEFAULT '',
            sujet        TEXT NOT NULL DEFAULT '',
            derniere_activite TEXT,
            cree_le      TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages_chat (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            auteur_type     TEXT NOT NULL,
            auteur_id       INTEGER NOT NULL,
            auteur_nom      TEXT NOT NULL DEFAULT '',
            contenu         TEXT NOT NULL DEFAULT '',
            photo_url       TEXT DEFAULT '',
            lu              INTEGER DEFAULT 0,
            cree_le         TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)
    # Index pour accélérer les requêtes
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_msg_conv
        ON messages_chat(conversation_id, cree_le)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_conv_p1
        ON conversations(participant_1_type, participant_1_id)
    """)
    con.execute("""
        CREATE INDEX IF NOT EXISTS idx_conv_p2
        ON conversations(participant_2_type, participant_2_id)
    """)
    con.commit()


# ──────────────────────────────────────────────────────────
#  Fonctions utilitaires
# ──────────────────────────────────────────────────────────

def trouver_ou_creer_conversation(con, type1, id1, nom1, type2, id2, nom2, sujet=""):
    """
    Trouve une conversation existante entre deux participants,
    ou en crée une nouvelle.
    Retourne l'ID de la conversation.
    """
    row = con.execute("""
        SELECT id FROM conversations
        WHERE (participant_1_type=? AND participant_1_id=? AND participant_2_type=? AND participant_2_id=?)
           OR (participant_1_type=? AND participant_1_id=? AND participant_2_type=? AND participant_2_id=?)
        ORDER BY derniere_activite DESC LIMIT 1
    """, (type1, id1, type2, id2, type2, id2, type1, id1)).fetchone()

    if row:
        return row[0]

    cur = con.execute("""
        INSERT INTO conversations
            (type, participant_1_type, participant_1_id, participant_1_nom,
             participant_2_type, participant_2_id, participant_2_nom,
             sujet, derniere_activite)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
    """, (f"{type1}-{type2}", type1, id1, nom1, type2, id2, nom2, sujet))
    con.commit()
    return cur.lastrowid


def conversations_de(con, type_participant, id_participant):
    """
    Liste toutes les conversations d'un participant, triées par activité récente.
    Retourne une liste de dicts avec infos du correspondant et dernier message.
    """
    rows = con.execute("""
        SELECT c.id, c.type, c.sujet, c.derniere_activite,
               c.participant_1_type, c.participant_1_id, c.participant_1_nom,
               c.participant_2_type, c.participant_2_id, c.participant_2_nom
        FROM conversations c
        WHERE (c.participant_1_type=? AND c.participant_1_id=?)
           OR (c.participant_2_type=? AND c.participant_2_id=?)
        ORDER BY c.derniere_activite DESC
    """, (type_participant, id_participant, type_participant, id_participant)).fetchall()

    conversations = []
    for r in rows:
        conv_id = r[0]
        # Déterminer le correspondant
        if r[4] == type_participant and r[5] == id_participant:
            corresp_type, corresp_id, corresp_nom = r[7], r[8], r[9]
        else:
            corresp_type, corresp_id, corresp_nom = r[4], r[5], r[6]

        # Dernier message
        dernier = con.execute("""
            SELECT contenu, auteur_nom, cree_le FROM messages_chat
            WHERE conversation_id=? ORDER BY cree_le DESC LIMIT 1
        """, (conv_id,)).fetchone()

        # Messages non lus
        non_lus = con.execute("""
            SELECT COUNT(*) FROM messages_chat
            WHERE conversation_id=? AND lu=0
              AND NOT (auteur_type=? AND auteur_id=?)
        """, (conv_id, type_participant, id_participant)).fetchone()[0]

        conversations.append({
            "id": conv_id,
            "type": r[1],
            "sujet": r[2],
            "derniere_activite": r[3],
            "correspondant_type": corresp_type,
            "correspondant_id": corresp_id,
            "correspondant_nom": corresp_nom,
            "dernier_message": dernier[0] if dernier else "",
            "dernier_auteur": dernier[1] if dernier else "",
            "dernier_date": dernier[2] if dernier else "",
            "non_lus": non_lus
        })

    return conversations


def envoyer_message(con, conv_id, auteur_type, auteur_id, auteur_nom, contenu, photo_url=""):
    """Envoie un message dans une conversation. Met à jour derniere_activite."""
    con.execute("""
        INSERT INTO messages_chat
            (conversation_id, auteur_type, auteur_id, auteur_nom, contenu, photo_url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (conv_id, auteur_type, auteur_id, auteur_nom, contenu, photo_url))
    con.execute("""
        UPDATE conversations SET derniere_activite=datetime('now','localtime')
        WHERE id=?
    """, (conv_id,))
    con.commit()


def lire_messages(con, conv_id, depuis=None, limite=50):
    """
    Lit les messages d'une conversation.
    Si `depuis` est fourni (ISO datetime), ne retourne que les messages plus récents.
    """
    if depuis:
        rows = con.execute("""
            SELECT id, auteur_type, auteur_id, auteur_nom, contenu, photo_url, lu, cree_le
            FROM messages_chat
            WHERE conversation_id=? AND cree_le>?
            ORDER BY cree_le ASC LIMIT ?
        """, (conv_id, depuis, limite)).fetchall()
    else:
        rows = con.execute("""
            SELECT id, auteur_type, auteur_id, auteur_nom, contenu, photo_url, lu, cree_le
            FROM messages_chat
            WHERE conversation_id=?
            ORDER BY cree_le DESC LIMIT ?
        """, (conv_id, limite)).fetchall()
        rows = list(reversed(rows))

    return [
        {
            "id": r[0], "auteur_type": r[1], "auteur_id": r[2],
            "auteur_nom": r[3], "contenu": r[4], "photo_url": r[5],
            "lu": r[6], "cree_le": r[7]
        }
        for r in rows
    ]


def marquer_lus(con, conv_id, lecteur_type, lecteur_id):
    """Marque tous les messages d'une conversation comme lus (sauf ceux de l'auteur)."""
    con.execute("""
        UPDATE messages_chat SET lu=1
        WHERE conversation_id=? AND lu=0
          AND NOT (auteur_type=? AND auteur_id=?)
    """, (conv_id, lecteur_type, lecteur_id))
    con.commit()


def compter_non_lus(con, type_participant, id_participant):
    """Compte le total de messages non lus pour un participant."""
    row = con.execute("""
        SELECT COUNT(*) FROM messages_chat m
        JOIN conversations c ON m.conversation_id = c.id
        WHERE m.lu = 0
          AND NOT (m.auteur_type=? AND m.auteur_id=?)
          AND (
              (c.participant_1_type=? AND c.participant_1_id=?)
           OR (c.participant_2_type=? AND c.participant_2_id=?)
          )
    """, (type_participant, id_participant,
          type_participant, id_participant,
          type_participant, id_participant)).fetchone()
    return row[0] if row else 0


def liste_contacts_disponibles(con, type_demandeur):
    """
    Retourne la liste des contacts possibles pour un type de participant.
    admin → tout le monde | partenaire → admin + livreurs | livreur → admin + partenaires | client → admin
    """
    contacts = []

    if type_demandeur in ("admin", "partenaire", "livreur"):
        # Livreurs
        if type_demandeur != "livreur":
            for r in con.execute("SELECT id, nom FROM livreurs WHERE actif=1").fetchall():
                contacts.append({"type": "livreur", "id": r[0], "nom": r[1]})
        # Partenaires
        if type_demandeur != "partenaire":
            for r in con.execute("SELECT id, nom FROM partenaires WHERE actif=1").fetchall():
                contacts.append({"type": "partenaire", "id": r[0], "nom": r[1]})

    # Admin est toujours disponible (sauf pour l'admin lui-même)
    if type_demandeur != "admin":
        contacts.append({"type": "admin", "id": 0, "nom": "Administration LIR"})

    return contacts
