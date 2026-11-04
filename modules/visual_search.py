# -*- coding: utf-8 -*-
"""
Module de recherche visuelle par photo — LIR Livraisons Express
Utilise Gemini Vision pour identifier un article à partir d'une photo
et chercher des correspondances dans le catalogue.
"""

import json
import os
import re
import base64
import datetime
import urllib.request


# ──────────────────────────────────────────────────────────
#  Prompts
# ──────────────────────────────────────────────────────────

PROMPT_VISION = """Tu es un assistant spécialisé dans l'identification de produits pour un service de livraison à Ouagadougou, Burkina Faso.

On te montre la photo d'un article qu'un client souhaite acheter ou faire livrer.

Analyse l'image et retourne un JSON avec :
{
  "description": "description courte du produit visible (en français)",
  "categorie": "une catégorie parmi : Alimentation, Médicaments, Cosmétiques, Vêtements, Électronique, Documents, Quincaillerie, Boissons, Autre",
  "mots_cles": ["mot1", "mot2", "mot3", "mot4", "mot5"],
  "couleur": "couleur principale si visible",
  "marque": "marque si visible, sinon vide"
}

Les mots-clés doivent être des termes de recherche utiles en français pour trouver ce produit dans un catalogue ouest-africain.
Retourne UNIQUEMENT le JSON, rien d'autre."""


# ──────────────────────────────────────────────────────────
#  Analyse d'image via Gemini
# ──────────────────────────────────────────────────────────

def analyser_image_produit(image_bytes, mime_type, api_key=None):
    """
    Envoie une image à Gemini Vision et retourne une description structurée.
    Retourne un dict : {description, categorie, mots_cles, couleur, marque}
    """
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return {"erreur": "Clé API Gemini non configurée"}

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    corps = {
        "contents": [{
            "parts": [
                {"text": PROMPT_VISION},
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": image_b64
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 500
        }
    }

    modeles = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]

    for modele in modeles:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent?key={api_key}"
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(corps).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            texte = data["candidates"][0]["content"]["parts"][0]["text"]
            # Extraire le JSON de la réponse
            texte = texte.strip()
            if texte.startswith("```"):
                texte = re.sub(r"^```\w*\n?", "", texte)
                texte = re.sub(r"\n?```$", "", texte)
            resultat = json.loads(texte)
            return resultat

        except Exception:
            continue

    return {"erreur": "Impossible d'analyser l'image avec Gemini"}


# ──────────────────────────────────────────────────────────
#  Recherche dans le catalogue
# ──────────────────────────────────────────────────────────

def rechercher_par_image(con, image_bytes, mime_type, api_key=None):
    """
    Analyse une photo et recherche des articles correspondants dans le catalogue.
    Retourne : {analyse: {...}, resultats: [{id, nom, prix, photo, score, ...}]}
    """
    analyse = analyser_image_produit(image_bytes, mime_type, api_key)

    if "erreur" in analyse:
        return {"analyse": analyse, "resultats": []}

    mots_cles = analyse.get("mots_cles", [])
    categorie = analyse.get("categorie", "")
    description = analyse.get("description", "")
    marque = analyse.get("marque", "")

    # Construire les termes de recherche
    termes = set()
    for mk in mots_cles:
        for mot in mk.lower().split():
            if len(mot) >= 3:
                termes.add(mot)
    if marque:
        for mot in marque.lower().split():
            if len(mot) >= 2:
                termes.add(mot)
    for mot in description.lower().split():
        if len(mot) >= 4:
            termes.add(mot)

    if not termes:
        return {"analyse": analyse, "resultats": []}

    # Rechercher dans articles
    conditions = []
    params = []
    for t in termes:
        conditions.append("(LOWER(a.nom) LIKE ? OR LOWER(COALESCE(a.description,'')) LIKE ? OR LOWER(COALESCE(a.rubrique,'')) LIKE ?)")
        pattern = f"%{t}%"
        params.extend([pattern, pattern, pattern])

    # Chercher les articles qui matchent au moins un terme
    # On fait un score basé sur le nombre de termes matchés
    sql = f"""
        SELECT a.id, a.nom, a.prix, a.photo, a.description, a.rubrique,
               a.dispo, p.nom as partenaire_nom,
               ({' + '.join(f"(CASE WHEN LOWER(a.nom) LIKE ? OR LOWER(COALESCE(a.description,'')) LIKE ? OR LOWER(COALESCE(a.rubrique,'')) LIKE ? THEN 1 ELSE 0 END)" for _ in termes)}) as score
        FROM articles a
        LEFT JOIN partenaires p ON a.partenaire_id = p.id
        WHERE ({' OR '.join(conditions)})
          AND a.dispo = 1
        ORDER BY score DESC, a.nom ASC
        LIMIT 20
    """
    # Paramètres pour les CASEs dans le score + paramètres pour le WHERE
    score_params = []
    for t in termes:
        pattern = f"%{t}%"
        score_params.extend([pattern, pattern, pattern])

    all_params = score_params + params

    try:
        rows = con.execute(sql, all_params).fetchall()
    except Exception:
        # Fallback : recherche simple
        rows = []
        for t in termes:
            pattern = f"%{t}%"
            rs = con.execute("""
                SELECT a.id, a.nom, a.prix, a.photo, a.description, a.rubrique,
                       a.dispo, p.nom as partenaire_nom, 1 as score
                FROM articles a
                LEFT JOIN partenaires p ON a.partenaire_id = p.id
                WHERE a.dispo = 1
                  AND (LOWER(a.nom) LIKE ? OR LOWER(COALESCE(a.description,'')) LIKE ?)
                LIMIT 10
            """, (pattern, pattern)).fetchall()
            rows.extend(rs)

    # Dédupliquer par ID
    vus = set()
    resultats = []
    for r in rows:
        if r[0] in vus:
            continue
        vus.add(r[0])
        resultats.append({
            "id": r[0],
            "nom": r[1],
            "prix": r[2],
            "photo": r[3] or "",
            "description": r[4] or "",
            "rubrique": r[5] or "",
            "dispo": r[6],
            "partenaire": r[7] or "",
            "score": r[8] if len(r) > 8 else 1
        })

    # Trier par score décroissant
    resultats.sort(key=lambda x: x["score"], reverse=True)

    return {
        "analyse": analyse,
        "resultats": resultats[:15]
    }


def sauvegarder_photo_recherche(image_bytes, ext="jpg"):
    """Sauvegarde la photo de recherche et retourne le chemin relatif."""
    dossier = os.path.join("static", "uploads", "recherches")
    os.makedirs(dossier, exist_ok=True)
    horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    nom_fichier = f"recherche_{horodatage}.{ext}"
    chemin = os.path.join(dossier, nom_fichier)
    with open(chemin, "wb") as f:
        f.write(image_bytes)
    return f"/static/uploads/recherches/{nom_fichier}"
