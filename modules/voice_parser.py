"""Module de transcription et compréhension de notes vocales pour LIR Livraisons.
Prend en charge le français burkinabè, le mooré et le dioula, avec reconnaissance
spécialisée des quartiers de Ouagadougou et extraction directe des informations de livraison.
"""

import os
import re
import json
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime

# Liste étendue des quartiers et repères de Ouagadougou pour guider l'IA
QUARTIERS_CONTEXTE = (
    "Ouagadougou, Ouaga 2000, Dassasgho, Wayalghin, Wemtenga, Somgandé, Pissy, "
    "Gounghin, Karpala, Patte d'oie, Tanghin, Tampouy, Zone 1, Zone du bois, "
    "Bogodogo, Cissin, Saaba, Kamboinssin, Nagrin, Toudbwéogo, Larlé, Samandin, "
    "Kalgondin, Sinyiri, Zogona, Bendogo, Rayongo, Paglayiri, Bonheur-ville, "
    "Boulmiougou, Donsin, Ziniaré, Lafiabougou, Nioko 1, Nioko 2, 1200 logements, "
    "Kouritenga, Balkuy, Poedogo, Yamtenga, Marcoussis, Rimkieta, Bissighin, "
    "Tingandogo, Petit Paris, Kamboinsé, Kossodo, Silmiougou."
)

LEXIQUE_LOCAL = (
    "Mooré fréquent : nansongho (prix/marché), laafi bala (salut), ya a woto (c'est ça), "
    "mam tondame (j'ai besoin), wa n diki (viens prendre), tall n kẽ (emmène chez), "
    "bãngr zĩiga (repère), pousram (merci/salutations), ligidi (argent).\n"
    "Dioula fréquent : i ni ce / i ni sogoma (salut), barika (merci), dôgô (boutique), "
    "ta ka taga (prends pour emmener), n'b'a fɛ (je veux), wari (argent), sira (route/goudron).\n"
    "Français local : six-mètres, goudron, maquis, pharmacie, plaque, réserve, feu tricolore."
)

PROMPT_AUDIO_SYSTEM = f"""Tu es l'assistant d'accueil vocal de LIR Livraisons Express à Ouagadougou (Burkina Faso).
On te transmet une note vocale envoyée par un client sur WhatsApp (qui peut être en français, en mooré, en dioula, ou un mélange des trois).

Quartiers et repères fréquents : {QUARTIERS_CONTEXTE}
Lexique local : {LEXIQUE_LOCAL}

Ta mission est double :
1. TRANSCRIPTION : Transcris fidèlement ce que dit la personne. Si la personne parle en mooré ou en dioula, donne la transcription puis une traduction claire en français entre parenthèses.
2. EXTRACTION STRUCTURÉE : Extrais les données utiles pour la livraison au format JSON.

Format obligatoire de ta réponse (UNIQUEMENT cet objet JSON sans markdown superflu) :
{{
  "transcription": "Texte exact transcrit et traduit si nécessaire",
  "langue_detectee": "français | mooré | dioula | mixte",
  "donnees": {{
    "client_nom": "",
    "client_tel": "",
    "collecte_lieu": "",
    "collecte_quartier": "",
    "destinataire_nom": "",
    "destinataire_tel": "",
    "livraison_adresse": "",
    "livraison_quartier": "",
    "colis": "description du colis ou produit",
    "valeur_produit": 0,
    "prix_course": 1000,
    "mode_paiement": "Espèces | Orange Money | Moov Money",
    "encaisse_course_prevu": "Livreur | Notre équipe | À préciser",
    "remarques": ""
  }}
}}

Règles pour les données :
- Les numéros de téléphone du Burkina comportent 8 chiffres (commencent par 5, 6, 7 ou 0).
- Si le lieu de collecte n'est pas précisé, laisse une chaîne vide "".
- Pour valeur_produit et prix_course : nombres entiers uniquement (en FCFA). Si inconnu, 0.
- Ne devine jamais un numéro ou un nom qui n'a pas été prononcé.
"""

DOSSIER_AUDIOS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "uploads", "audios")


def assurer_dossier_audios() -> str:
    """S'assure que le dossier de stockage des fichiers audio existe."""
    os.makedirs(DOSSIER_AUDIOS, exist_ok=True)
    return DOSSIER_AUDIOS


def sauvegarder_audio_local(donnees_octets: bytes, extension: str = "ogg", prefixe: str = "wa") -> str:
    """Sauvegarde les octets audio sur le disque et retourne le chemin relatif accessible via Flask."""
    dossier = assurer_dossier_audios()
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    nom_fichier = f"{prefixe}_{horodatage}_{os.urandom(3).hex()}.{extension.lstrip('.')}"
    chemin_complet = os.path.join(dossier, nom_fichier)
    with open(chemin_complet, "wb") as f:
        f.write(donnees_octets)
    return f"/static/uploads/audios/{nom_fichier}"


def analyser_audio_gemini(donnees_octets: bytes, mime_type: str = "audio/ogg", api_key: str = "") -> dict:
    """Appelle Gemini Multimodal pour transcrire et structurer l'audio en français/mooré/dioula."""
    cle = (api_key or os.environ.get("GEMINI_API_KEY", "")).strip()
    if not cle:
        raise ValueError("Clé API GEMINI_API_KEY non configurée pour la transcription audio.")

    mime_propre = mime_type.split(";")[0].strip() or "audio/ogg"
    b64_audio = base64.b64encode(donnees_octets).decode("ascii")

    modeles = [
        os.environ.get("GEMINI_MODEL", "").strip(),
        "gemini-flash-lite-latest",
        "gemini-2.5-flash",
        "gemini-flash-latest"
    ]
    modeles = [m for m in modeles if m]

    corps = {
        "contents": [{
            "parts": [
                {"text": PROMPT_AUDIO_SYSTEM},
                {
                    "inline_data": {
                        "mime_type": mime_propre,
                        "data": b64_audio
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024
        }
    }

    derniere_erreur = None
    for modele in modeles:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
        req = urllib.request.Request(
            url,
            data=json.dumps(corps).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": cle}
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                reponse = json.loads(resp.read().decode("utf-8"))
                texte = reponse["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Nettoyage d'éventuels backticks markdown json
                texte_propre = re.sub(r"^```(?:json)?\s*", "", texte)
                texte_propre = re.sub(r"\s*```$", "", texte_propre)
                debut, fin = texte_propre.find("{"), texte_propre.rfind("}")
                if debut != -1 and fin != -1:
                    return json.loads(texte_propre[debut:fin + 1])
                return {"transcription": texte, "donnees": {}}
        except urllib.error.HTTPError as e:
            derniere_erreur = e
            if e.code in (404, 429, 500, 502, 503, 504):
                time.sleep(1)
                continue
            raise
        except Exception as e:
            derniere_erreur = e
            continue

    if derniere_erreur:
        raise derniere_erreur
    raise RuntimeError("Aucun modèle Gemini n'a pu traiter la note vocale.")
