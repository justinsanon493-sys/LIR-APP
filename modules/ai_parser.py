"""Module d'analyse intelligente de messages de livraison.
Fournit une extraction robuste par IA (Claude) ou par règles heuristiques locales.
"""
import re
import os

# Quartiers et repères fréquents à Ouagadougou pour la détection automatique
QUARTIERS_OUAGA = [
    "Koulouba", "Ouaga 2000", "Dassasgho", "Wayalghin", "Wemtenga", "Somgandé",
    "Pissy", "Gounghin", "Karpala", "Patte d'oie", "Tanghin", "Tampouy",
    "Zone 1", "Zone du bois", "Bogodogo", "Cissin", "Saaba", "Kamboinssin",
    "Nagrin", "Toudbwéogo", "Larlé", "Samandin", "Kalgondin", "Sinyiri",
    "Zogona", "Bendogo", "Rayongo", "Paglayiri", "Pagalayiri", "Bonheur-ville",
    "Bonheur ville", "Boulmiougou", "Donsin", "Ziniaré", "Lafiabougou",
    "Nioko 1", "Nioko 2", "1200 logements"
]

def normaliser_chiffres(tel: str) -> str:
    """Nettoie le numéro pour ne garder que les 8 chiffres locaux."""
    s = re.sub(r"\D", "", str(tel or ""))
    if s.startswith("226") and len(s) > 8:
        s = s[3:]
    return s

def nettoyer_nom(nom: str) -> str:
    """Nettoie les résidus après le nom."""
    if not nom:
        return ""
    n = re.sub(r"\s+(?:au|a|à|tel|tél|sur|avec|le|la|pour)\s*$", "", nom.strip(), flags=re.IGNORECASE)
    return n.strip(" :,-")

def extraire_par_regles_locales(texte: str) -> dict:
    """Extraction heuristique locale sans nécessiter d'appel externe ou de clé API."""
    donnees = {
        "canal": "WhatsApp",
        "client_nom": "",
        "client_tel": "",
        "collecte_lieu": "",
        "collecte_quartier": "",
        "livraison_adresse": "",
        "livraison_quartier": "",
        "destinataire_nom": "",
        "destinataire_tel": "",
        "colis": "",
        "valeur_produit": "",
        "prix_course": "1000",
        "mode_paiement": "Espèces",
        "encaisse_course_prevu": "Livreur",
        "statut_paiement": "en attente",
        "statut": "en attente",
        "remarques": ""
    }

    lignes = [l.strip() for l in texte.splitlines() if l.strip()]

    # 1. Extraction des téléphones
    telephones = re.findall(r"(?:(?:\+?226)|(?:\b))([5670][0-9](?:[\s.-]?[0-9]{2}){3})\b", texte)
    telephones_propres = [normaliser_chiffres(t) for t in telephones if len(normaliser_chiffres(t)) == 8]
    vus = set()
    telephones_uniques = [x for x in telephones_propres if not (x in vus or vus.add(x))]

    if len(telephones_uniques) >= 2:
        donnees["client_tel"] = telephones_uniques[0]
        donnees["destinataire_tel"] = telephones_uniques[1]
    elif len(telephones_uniques) == 1:
        donnees["destinataire_tel"] = telephones_uniques[0]

    # 2. Détection du mode de paiement
    texte_lower = texte.lower()
    if any(k in texte_lower for k in ("orange money", "om", "orange")):
        donnees["mode_paiement"] = "Orange Money"
    elif any(k in texte_lower for k in ("moov money", "mobicash", "moov", "flooz")):
        donnees["mode_paiement"] = "Mobi Cash"
    elif "sank" in texte_lower:
        donnees["mode_paiement"] = "Sank Money"
    else:
        donnees["mode_paiement"] = "Espèces"

    # 3. Montants en FCFA (sécuriser "Ouaga 2000")
    texte_sans_ouaga2000 = re.sub(r"ouaga\s*2000", "ouaga_deux_mille", texte, flags=re.IGNORECASE)
    
    match_course = re.search(r"(?:course|livraison|frais)\s*:?\s*(\d+[\d\s]*)\s*(?:f|cfa|fcfa)?\b", texte_sans_ouaga2000, re.IGNORECASE)
    if match_course:
        try:
            val_c = int(re.sub(r"[^\d]", "", match_course.group(1)))
            if 500 <= val_c <= 10000:
                donnees["prix_course"] = str(val_c)
        except Exception:
            pass

    match_valeur = re.search(r"(?:valeur|prix|montant|cout|coût|total|articles?|colis)\s*:?\s*(\d+[\d\s]*)\s*(?:f|cfa|fcfa)\b", texte_sans_ouaga2000, re.IGNORECASE)
    if match_valeur:
        try:
            val_p = int(re.sub(r"[^\d]", "", match_valeur.group(1)))
            donnees["valeur_produit"] = str(val_p)
        except Exception:
            pass
    else:
        montants = re.findall(r"(\d+[\d\s]*)\s*(?:f|cfa|fcfa)\b", texte_sans_ouaga2000, re.IGNORECASE)
        valeurs_num = [int(re.sub(r"[^\d]", "", m)) for m in montants if re.sub(r"[^\d]", "", m)]
        montants_produit = [m for m in valeurs_num if str(m) != donnees.get("prix_course")]
        if montants_produit:
            donnees["valeur_produit"] = str(montants_produit[0])

    # 4. Détection fine des quartiers et sens collecte -> livraison
    quartiers_trouves = []
    for q in QUARTIERS_OUAGA:
        idx = texte_lower.find(q.lower())
        if idx != -1:
            quartiers_trouves.append((idx, q))
    quartiers_trouves.sort(key=lambda x: x[0])
    quartiers_noms = [q[1] for q in quartiers_trouves]

    # Analyse des contextes autour des quartiers
    q_collecte = ""
    q_livraison = ""

    for q in quartiers_noms:
        idx = texte_lower.find(q.lower())
        segment_avant = texte_lower[max(0, idx-30):idx]
        if any(m in segment_avant for m in ("collecte", "depart", "départ", "ramassage", "recuperer", "récupérer", "ramasser", "de")):
            if not q_collecte:
                q_collecte = q
        elif any(m in segment_avant for m in ("livrer", "livraison", "deposer", "déposer", "vers", "destination", "pour", "chez")):
            if not q_livraison:
                q_livraison = q

    # S'ils ne sont pas assignés par contexte
    if not q_collecte and not q_livraison:
        if len(quartiers_noms) >= 2:
            q_collecte, q_livraison = quartiers_noms[0], quartiers_noms[1]
        elif len(quartiers_noms) == 1:
            q_livraison = quartiers_noms[0]
    elif q_collecte and not q_livraison:
        autres = [q for q in quartiers_noms if q != q_collecte]
        if autres:
            q_livraison = autres[0]
    elif q_livraison and not q_collecte:
        autres = [q for q in quartiers_noms if q != q_livraison]
        if autres:
            q_collecte = autres[0]

    donnees["collecte_quartier"] = q_collecte
    donnees["livraison_quartier"] = q_livraison

    # 5. Détection des noms
    match_dest_nom = re.search(r"(?:destinataire|pour|client|remettre à|remettre a|chez)\s*:?\s*(?:m\.|mme|monsieur|madame)?\s*([A-Za-zÀ-ÿ\s'-]{2,35}?)(?:,|\.|\n|tel|tél|\d|au\s+\d|à\s+[A-Z]|$)", texte, re.IGNORECASE)
    if match_dest_nom:
        donnees["destinataire_nom"] = nettoyer_nom(match_dest_nom.group(1))
    elif not donnees["destinataire_nom"]:
        match_civilite = re.search(r"\b(?:m\.|mme|monsieur|madame)\s+([A-Za-zÀ-ÿ\s'-]{2,30}?)(?:,|\.|\n|tel|tél|\d|au\s+\d|$)", texte, re.IGNORECASE)
        if match_civilite:
            donnees["destinataire_nom"] = nettoyer_nom(match_civilite.group(0))

    match_exp = re.search(r"(?:expéditeur|expediteur|vendeur|magasin|de la part de)\s*:?\s*([A-Za-zÀ-ÿ0-9\s'-]{3,35})(?:,|\.|\n|tel|tél|\d|$)", texte, re.IGNORECASE)
    if match_exp:
        donnees["client_nom"] = nettoyer_nom(match_exp.group(1))

    # 6. Repère / Adresse de livraison et collecte
    match_repere = re.search(r"(?:adresse|repère|repere|lieu|position|indication)\s*:?\s*([^,\n]+)", texte, re.IGNORECASE)
    if match_repere:
        donnees["livraison_adresse"] = match_repere.group(1).strip()
    else:
        match_loc = re.search(r"\b((?:face|près|pres|proche|derrière|derriere|non loin|à côté|a cote|carrefour|échangeur|rond-point|immeuble|villa)\s+[^,\n.]+)", texte, re.IGNORECASE)
        if match_loc:
            donnees["livraison_adresse"] = match_loc.group(1).strip()

    # 7. Colis
    match_colis = re.search(r"(?:colis|produit|article|commande)\s*:?\s*([^,\n]+)", texte, re.IGNORECASE)
    if match_colis:
        donnees["colis"] = match_colis.group(1).strip()
    elif lignes:
        for l in lignes:
            if not re.search(r"^\s*(bonjour|salut|merci|coursier|livraison|destinataire)", l, re.IGNORECASE):
                donnees["colis"] = l[:60]
                break
        if not donnees["colis"]:
            donnees["colis"] = "Colis / Marchandise"

    return donnees

def analyser_message_commande(texte: str, api_key: str = None) -> dict:
    """Analyse un message client avec Claude si clé dispo, sinon fallback local garanti."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return extraire_par_regles_locales(texte)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = f"""Tu es l'assistant de saisie de courses de livraison à Ouagadougou.
Analyse ce message et extrais les informations au format JSON strict avec exactement ces clés :
- client_nom (texte ou "")
- client_tel (8 chiffres ou "")
- collecte_lieu (texte ou "")
- collecte_quartier (quartier de collecte ou "")
- livraison_adresse (repère ou adresse ou "")
- livraison_quartier (quartier de livraison ou "")
- destinataire_nom (nom du destinataire ou "")
- destinataire_tel (téléphone du destinataire ou "")
- colis (description brève du produit/colis)
- valeur_produit (nombre entier en FCFA ou "")
- prix_course (nombre entier en FCFA ou "1000")
- mode_paiement ("Espèces", "Orange Money", "Mobi Cash" ou "Sank Money")
- encaisse_course_prevu ("Livreur", "Notre équipe", ou "À préciser")

Message à analyser :
\"\"\"{texte}\"\"\"

Réponds UNIQUEMENT avec l'objet JSON valide, sans texte additionnel."""

        reponse = client.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-3-5-sonnet-20241022"),
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        contenu = reponse.content[0].text.strip()
        match_json = re.search(r"\{.*\}", contenu, re.DOTALL)
        if match_json:
            import json
            return json.loads(match_json.group(0))
        return extraire_par_regles_locales(texte)
    except Exception as e:
        return extraire_par_regles_locales(texte)
