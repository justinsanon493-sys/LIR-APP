"""Module SaaS Multi-Entreprises pour LIR Livraisons.
Permet d'héberger plusieurs agences et sociétés de livraison indépendantes sur la même plateforme :
- Isolation des livraisons, livreurs, partenaires et caisses par entreprise (entreprise_id).
- Gestion des abonnements mensuels, activation/désactivation de comptes.
- Tableau de bord Super-Admin pour superviser tout le réseau.
"""

import sqlite3
from datetime import datetime, timedelta

def initialiser_tables_saas(con):
    """Crée la table des entreprises et ajoute entreprise_id aux tables principales."""
    con.execute("""
    CREATE TABLE IF NOT EXISTS entreprises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        responsable TEXT DEFAULT '',
        tel TEXT DEFAULT '',
        email TEXT DEFAULT '',
        ville TEXT DEFAULT 'Ouagadougou',
        devise TEXT DEFAULT 'FCFA',
        prix_course_defaut REAL DEFAULT 1000,
        commission_defaut REAL DEFAULT 10,
        logo TEXT DEFAULT '',
        actif INTEGER DEFAULT 1,
        formule TEXT DEFAULT 'pro',
        expire_le TEXT,
        cree_le TEXT NOT NULL
    );
    """)

    # S'assurer que l'entreprise par défaut (LIR) existe avec l'ID 1
    existe = con.execute("SELECT id FROM entreprises WHERE id=1").fetchone()
    if not existe:
        con.execute("""
        INSERT INTO entreprises (id, nom, slug, responsable, tel, ville, actif, formule, expire_le, cree_le)
        VALUES (1, 'LIR - Livreur d''Intervention Rapide', 'lir-express', 'SANON Justin', '07 60 66 77 / 55 28 82 36', 'Ouagadougou', 1, 'illimité', '2099-12-31', ?)
        """, (datetime.now().strftime("%Y-%m-%d %H:%M"),))

    # Ajouter entreprise_id aux tables métier si pas déjà fait
    tables = ["livraisons", "livreurs", "partenaires", "contacts", "mouvements_caisse"]
    for t in tables:
        try:
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            if "entreprise_id" not in cols:
                con.execute(f"ALTER TABLE {t} ADD COLUMN entreprise_id INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass

    # Table de facturation des abonnements SaaS
    con.execute("""
    CREATE TABLE IF NOT EXISTS abonnements_saas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        entreprise_id INTEGER NOT NULL,
        montant REAL NOT NULL,
        moyen_paiement TEXT DEFAULT 'Orange Money',
        reference_paiement TEXT DEFAULT '',
        periode_mois INTEGER DEFAULT 1,
        paye_le TEXT NOT NULL,
        nouvelle_expiration TEXT NOT NULL,
        note TEXT DEFAULT '',
        FOREIGN KEY (entreprise_id) REFERENCES entreprises(id)
    );
    """)


def lister_entreprises(con, actif_seulement=False):
    """Retourne toutes les entreprises avec leurs statistiques globales."""
    where = "WHERE e.actif=1" if actif_seulement else ""
    sql = f"""
    SELECT e.*,
           (SELECT COUNT(*) FROM livraisons l WHERE l.entreprise_id=e.id) AS total_livraisons,
           (SELECT COUNT(*) FROM livreurs lv WHERE lv.entreprise_id=e.id AND lv.actif=1) AS livreurs_actifs,
           (SELECT COUNT(*) FROM partenaires p WHERE p.entreprise_id=e.id AND p.actif=1) AS partenaires_actifs
    FROM entreprises e
    {where}
    ORDER BY e.id ASC
    """
    return [dict(r) for r in con.execute(sql).fetchall()]


def creer_entreprise(con, nom, slug, responsable="", tel="", ville="Ouagadougou", formule="pro", jours_validite=30):
    """Crée une nouvelle entreprise avec une période d'essai ou d'abonnement."""
    exp = (datetime.now() + timedelta(days=jours_validite)).strftime("%Y-%m-%d")
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M")
    cur = con.execute("""
    INSERT INTO entreprises (nom, slug, responsable, tel, ville, formule, expire_le, cree_le)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (nom.strip(), slug.strip().lower(), responsable.strip(), tel.strip(), ville.strip(), formule, exp, maintenant))
    return cur.lastrowid


def prolonger_abonnement(con, entreprise_id, mois=1, montant=50000, moyen="Orange Money", reference="", note=""):
    """Prolonge l'abonnement d'une entreprise suite à son paiement."""
    ent = con.execute("SELECT expire_le FROM entreprises WHERE id=?", (entreprise_id,)).fetchone()
    if not ent:
        raise ValueError("Entreprise introuvable")

    exp_actuelle = ent[0]
    base_date = datetime.now().date()
    if exp_actuelle:
        try:
            d = datetime.strptime(exp_actuelle[:10], "%Y-%m-%d").date()
            if d > base_date:
                base_date = d
        except Exception:
            pass

    nouvelle_exp = (base_date + timedelta(days=30 * mois)).strftime("%Y-%m-%d")
    maintenant = datetime.now().strftime("%Y-%m-%d %H:%M")

    con.execute("UPDATE entreprises SET expire_le=?, actif=1 WHERE id=?", (nouvelle_exp, entreprise_id))
    con.execute("""
    INSERT INTO abonnements_saas (entreprise_id, montant, moyen_paiement, reference_paiement, periode_mois, paye_le, nouvelle_expiration, note)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (entreprise_id, montant, moyen, reference, mois, maintenant, nouvelle_exp, note))
    return nouvelle_exp
