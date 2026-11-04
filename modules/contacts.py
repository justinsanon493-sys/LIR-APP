"""Module Répertoire Universel de Contacts pour LIR Livraisons
Centralise tous les contacts (clients, destinataires, partenaires, livreurs)
et offre une recherche intelligente et l'auto-remplissage des champs.
"""
import re
import unicodedata
from datetime import datetime

def normaliser_tel(s: str) -> str:
    """Conserve uniquement les chiffres et retire l'indicatif 226 s'il dépasse 8 chiffres."""
    t = re.sub(r"\D", "", str(s or ""))
    if t.startswith("226") and len(t) > 8:
        t = t[3:]
    return t

def normaliser_texte(t: str) -> str:
    """Supprime accents et majuscules pour une recherche insensible."""
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if unicodedata.category(c) != "Mn").strip()

def initialiser_table_contacts(con):
    """Crée la table contacts et ses index si nécessaire."""
    con.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT DEFAULT '',
            tel TEXT UNIQUE,
            quartier TEXT DEFAULT '',
            adresse TEXT DEFAULT '',
            role TEXT DEFAULT 'client',
            type_client TEXT DEFAULT 'Particulier',
            nb_commandes INTEGER DEFAULT 1,
            dernier_passage TEXT DEFAULT '',
            mode_paiement TEXT DEFAULT 'Espèces',
            remarques TEXT DEFAULT '',
            cree_le TEXT DEFAULT ''
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_contacts_tel ON contacts(tel)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_contacts_nom ON contacts(nom)")

def synchroniser_contacts_depuis_historique(con):
    """Parcourt l'historique des livraisons, partenaires et livreurs pour alimenter le répertoire."""
    initialiser_table_contacts(con)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Clients depuis livraisons
    clients = con.execute("""
        SELECT client_nom, client_tel, client_quartier, collecte_lieu, collecte_quartier, 
               mode_paiement, type_client, cree_le 
        FROM livraisons 
        WHERE client_tel IS NOT NULL AND TRIM(client_tel) != ''
        ORDER BY id ASC
    """).fetchall()

    for r in clients:
        tel = normaliser_tel(r["client_tel"])
        if not tel or len(tel) < 8:
            continue
        nom = (r["client_nom"] or "").strip()
        quartier = (r["client_quartier"] or r["collecte_quartier"] or "").strip()
        adresse = (r["collecte_lieu"] or "").strip()
        mode_paiement = r["mode_paiement"] or "Espèces"
        type_client = r["type_client"] or "Particulier"
        date_cmd = r["cree_le"] or now

        existant = con.execute("SELECT id, nb_commandes, nom, quartier, adresse FROM contacts WHERE tel=?", (tel,)).fetchone()
        if existant:
            nouveau_nom = nom or existant["nom"]
            nouveau_quartier = quartier or existant["quartier"]
            nouvelle_adresse = adresse or existant["adresse"]
            con.execute("""
                UPDATE contacts 
                SET nom=?, quartier=?, adresse=?, nb_commandes=nb_commandes+1, 
                    dernier_passage=?, mode_paiement=?
                WHERE id=?
            """, (nouveau_nom, nouveau_quartier, nouvelle_adresse, date_cmd, mode_paiement, existant["id"]))
        else:
            con.execute("""
                INSERT OR IGNORE INTO contacts (nom, tel, quartier, adresse, role, type_client, nb_commandes, dernier_passage, mode_paiement, cree_le)
                VALUES (?, ?, ?, ?, 'client', ?, 1, ?, ?, ?)
            """, (nom, tel, quartier, adresse, type_client, date_cmd, mode_paiement, date_cmd))

    # 2. Destinataires depuis livraisons
    destinataires = con.execute("""
        SELECT destinataire_nom, destinataire_tel, livraison_quartier, livraison_adresse, cree_le 
        FROM livraisons 
        WHERE destinataire_tel IS NOT NULL AND TRIM(destinataire_tel) != ''
        ORDER BY id ASC
    """).fetchall()

    for r in destinataires:
        tel = normaliser_tel(r["destinataire_tel"])
        if not tel or len(tel) < 8:
            continue
        nom = (r["destinataire_nom"] or "").strip()
        quartier = (r["livraison_quartier"] or "").strip()
        adresse = (r["livraison_adresse"] or "").strip()
        date_cmd = r["cree_le"] or now

        existant = con.execute("SELECT id, nb_commandes, nom, quartier, adresse, role FROM contacts WHERE tel=?", (tel,)).fetchone()
        if existant:
            nouveau_nom = nom or existant["nom"]
            nouveau_quartier = quartier or existant["quartier"]
            nouvelle_adresse = adresse or existant["adresse"]
            con.execute("""
                UPDATE contacts 
                SET nom=?, quartier=?, adresse=?, nb_commandes=nb_commandes+1, dernier_passage=?
                WHERE id=?
            """, (nouveau_nom, nouveau_quartier, nouvelle_adresse, date_cmd, existant["id"]))
        else:
            con.execute("""
                INSERT OR IGNORE INTO contacts (nom, tel, quartier, adresse, role, type_client, nb_commandes, dernier_passage, mode_paiement, cree_le)
                VALUES (?, ?, ?, ?, 'destinataire', 'Destinataire', 1, ?, 'Espèces', ?)
            """, (nom, tel, quartier, adresse, date_cmd, date_cmd))

    # 3. Partenaires
    try:
        partenaires = con.execute("""
            SELECT nom, tel, quartier, adresse, categorie FROM partenaires WHERE tel IS NOT NULL AND TRIM(tel) != ''
        """).fetchall()
        for p in partenaires:
            tel = normaliser_tel(p["tel"])
            if not tel or len(tel) < 8:
                continue
            nom = (p["nom"] or "").strip()
            quartier = (p["quartier"] or "").strip()
            adresse = (p["adresse"] or "").strip()
            cat = p["categorie"] or "Partenaire"

            existant = con.execute("SELECT id FROM contacts WHERE tel=?", (tel,)).fetchone()
            if existant:
                con.execute("UPDATE contacts SET nom=?, quartier=?, adresse=?, role='partenaire', type_client=? WHERE id=?",
                            (nom, quartier, adresse, cat, existant["id"]))
            else:
                con.execute("""
                    INSERT OR IGNORE INTO contacts (nom, tel, quartier, adresse, role, type_client, nb_commandes, dernier_passage, mode_paiement, cree_le)
                    VALUES (?, ?, ?, ?, 'partenaire', ?, 1, ?, 'Espèces', ?)
                """, (nom, tel, quartier, adresse, cat, now, now))
    except Exception:
        pass

def enregistrer_ou_maj_contact(con, tel: str, nom: str = "", quartier: str = "", adresse: str = "", 
                               role: str = "client", mode_paiement: str = "", type_client: str = ""):
    """Enregistre ou met à jour un contact lors d'une nouvelle course ou modification."""
    t = normaliser_tel(tel)
    if not t or len(t) < 8:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    existant = con.execute("SELECT id, nom, quartier, adresse, role, nb_commandes FROM contacts WHERE tel=?", (t,)).fetchone()
    if existant:
        nouveau_nom = nom.strip() if nom.strip() else existant["nom"]
        nouveau_quartier = quartier.strip() if quartier.strip() else existant["quartier"]
        nouvelle_adresse = adresse.strip() if adresse.strip() else existant["adresse"]
        nouveau_role = role if role in ('partenaire', 'client') or existant["role"] == 'destinataire' else existant["role"]
        con.execute("""
            UPDATE contacts 
            SET nom=?, quartier=?, adresse=?, role=?, nb_commandes=nb_commandes+1, dernier_passage=?,
                mode_paiement=COALESCE(NULLIF(?,''), mode_paiement),
                type_client=COALESCE(NULLIF(?,''), type_client)
            WHERE id=?
        """, (nouveau_nom, nouveau_quartier, nouvelle_adresse, nouveau_role, now, mode_paiement, type_client, existant["id"]))
    else:
        con.execute("""
            INSERT INTO contacts (nom, tel, quartier, adresse, role, type_client, nb_commandes, dernier_passage, mode_paiement, cree_le)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (nom.strip(), t, quartier.strip(), adresse.strip(), role, type_client or 'Particulier', now, mode_paiement or 'Espèces', now))

def trouver_contact_par_tel(con, tel: str):
    """Retrouve un contact unique par son numéro normalisé."""
    t = normaliser_tel(tel)
    if not t or len(t) < 8:
        return None
    r = con.execute("SELECT * FROM contacts WHERE tel=?", (t,)).fetchone()
    return dict(r) if r else None

def rechercher_contacts(con, q: str, limite: int = 8) -> list:
    """Recherche dynamique de contacts par numéro ou nom ou quartier."""
    q = (q or "").strip()
    if len(q) < 2:
        return []
    
    qd = re.sub(r"\D", "", q)
    qn = normaliser_texte(q)
    
    resultats = []
    # Recherche par numéro
    if len(qd) >= 2:
        lignes = con.execute("""
            SELECT * FROM contacts 
            WHERE tel LIKE ? OR tel LIKE ?
            ORDER BY nb_commandes DESC, dernier_passage DESC LIMIT ?
        """, (f"%{qd}%", f"%{qd[-8:]}%", limite)).fetchall()
        for l in lignes:
            d = dict(l)
            if d not in resultats:
                resultats.append(d)

    # Recherche par nom ou quartier si encore de la place
    if len(resultats) < limite and len(qn) >= 2:
        lignes = con.execute("""
            SELECT * FROM contacts 
            WHERE LOWER(nom) LIKE ? OR LOWER(quartier) LIKE ? OR LOWER(adresse) LIKE ?
            ORDER BY nb_commandes DESC, dernier_passage DESC LIMIT ?
        """, (f"%{qn}%", f"%{qn}%", f"%{qn}%", limite - len(resultats))).fetchall()
        for l in lignes:
            d = dict(l)
            if not any(r["id"] == d["id"] for r in resultats):
                resultats.append(d)

    return resultats[:limite]
