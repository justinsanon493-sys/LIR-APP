"""Module WhatsApp pour LIR Livraisons
Génère des liens et messages WhatsApp pré-remplis pour clients, destinataires et livreurs.
"""
import urllib.parse
import re

def nettoyer_telephone(tel: str) -> str:
    """Nettoie et formate un numéro de téléphone pour WhatsApp."""
    if not tel:
        return ""
    # Garder uniquement les chiffres
    chiffres = re.sub(r"[^\d]", "", str(tel))
    # Cas typique Burkina Faso (8 chiffres sans indicatif)
    if len(chiffres) == 8:
        return f"226{chiffres}"
    # Déjà au format international 226XXXXXXXX
    if len(chiffres) == 11 and chiffres.startswith("226"):
        return chiffres
    return chiffres

def formater_fcfa(montant) -> str:
    """Formate un montant en FCFA avec des espaces (ex: 15 000 FCFA)."""
    try:
        val = int(montant or 0)
        return f"{val:,}".replace(",", " ") + " FCFA"
    except (ValueError, TypeError):
        return "0 FCFA"

def message_client_prise_en_charge(livraison: dict, base_url: str = "") -> str:
    """Message envoyé au client pour confirmer la prise en charge de sa course."""
    numero = livraison.get("numero") or f"#{livraison.get('id', '')}"
    dest = livraison.get("destinataire_nom") or "le destinataire"
    lieu_livraison = livraison.get("livraison_quartier") or livraison.get("livraison_adresse") or "lieu convenu"
    prix = formater_fcfa(livraison.get("prix_course", 0))
    livreur = livraison.get("livreur") or "Notre livreur"

    lien_suivi = f"{base_url.rstrip('/')}/suivi/{numero}" if base_url else ""

    msg = (
        f"Bonjour ! Votre livraison *{numero}* pour *{dest}* ({lieu_livraison}) "
        f"a bien été enregistrée.\n"
        f"🏍️ Livreur : {livreur}\n"
        f"💰 Prix de la course : {prix}\n"
    )
    if lien_suivi:
        msg += f"\n📍 Suivez votre coursier en direct sur la carte :\n{lien_suivi}\n"

    if base_url:
        msg += (f"\n📲 Ouvrez LIR pour commander et suivre vos colis :\n{base_url.rstrip('/')}/rejoindre\n"
                "LIR s’ouvre comme une page sécurisée. L’ajout d’une icône sur l’écran d’accueil est facultatif.\n")

    msg += "\nMerci pour votre confiance avec LIR Livraisons !"
    return msg

def message_destinataire(livraison: dict, base_url: str = "") -> str:
    """Message envoyé au destinataire pour l'informer de l'arrivée du colis et lui proposer nos services."""
    numero = livraison.get("numero") or f"#{livraison.get('id', '')}"
    colis = livraison.get("colis") or "votre colis"
    valeur = livraison.get("valeur_produit", 0) or 0
    prix_course = livraison.get("prix_course", 0) or 0
    encaisse_prevu = livraison.get("encaisse_course_prevu")
    
    total_a_payer = valeur
    if encaisse_prevu == "Livreur":
        total_a_payer += prix_course

    livreur = livraison.get("livreur") or "notre coursier"
    lien_suivi = f"{base_url.rstrip('/')}/suivi/{numero}" if base_url else ""
    lien_commande = f"{base_url.rstrip('/')}/rejoindre" if base_url else ""

    msg = (
        f"Bonjour ! Un colis ({colis}) est en cours d'acheminement vers vous.\n"
        f"🏍️ Coursier LIR : *{livreur}*\n"
    )
    if total_a_payer > 0:
        msg += f"💵 Montant total à préparer : *{formater_fcfa(total_a_payer)}*\n"

    if lien_suivi:
        msg += f"\n🛰️ Suivez le coursier en direct sur la carte :\n{lien_suivi}\n"

    # --- Stratégie d'acquisition virale ---
    msg += (
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"✨ *BESOIN D'ENVOYER UN COLIS OU UN REPAS ?*\n"
        f"LIR livre partout à Ouagadougou en moins de 45 min !\n"
    )
    if lien_commande:
        msg += (f"📲 Ouvrez gratuitement LIR pour commander, suivre un colis ou demander un compte :\n{lien_commande}\n"
                "LIR s’ouvre comme une page sécurisée ; aucun fichier d’application n’est téléchargé.\n")
    else:
        msg += "📲 Écrivez-nous sur ce numéro pour commander votre coursier !\n"

    msg += "━━━━━━━━━━━━━━━━━━\nMerci de rester joignable pour la réception !"
    return msg


def message_fiche_livreur(livraison: dict) -> str:
    """Fiche synthétique envoyée au livreur avec toutes les instructions."""
    numero = livraison.get("numero") or f"#{livraison.get('id', '')}"
    collecte = f"{livraison.get('collecte_lieu', '')} ({livraison.get('collecte_quartier', '')})".strip()
    client_tel = livraison.get("client_tel", "")
    dest_tel = livraison.get("destinataire_tel", "")
    livr_adr = f"{livraison.get('livraison_adresse', '')} ({livraison.get('livraison_quartier', '')})".strip()
    colis = livraison.get("colis", "")
    valeur = formater_fcfa(livraison.get("valeur_produit", 0))
    prix_course = formater_fcfa(livraison.get("prix_course", 0))
    encaisse = livraison.get("encaisse_course_prevu", "")

    msg = (
        f"📦 *MISSION LIVRAISON {numero}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📍 *RAMASSAGE* : {collecte}\n"
        f"📞 Tél ramassage : {client_tel}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *LIVRAISON* : {livr_adr}\n"
        f"👤 Destinataire : {livraison.get('destinataire_nom', '')}\n"
        f"📞 Tél destinataire : {dest_tel}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 Colis : {colis}\n"
        f"💵 Prix course : {prix_course}\n"
        f"💰 Valeur produit : {valeur}\n"
        f"👉 À encaisser : {encaisse}\n"
    )
    return msg


def generer_lien_whatsapp(numero_tel: str, message: str) -> str:
    """Génère le lien web https://wa.me/"""
    tel_propre = nettoyer_telephone(numero_tel)
    msg_encode = urllib.parse.quote(message)
    if tel_propre:
        return f"https://wa.me/{tel_propre}?text={msg_encode}"
    return f"https://wa.me/?text={msg_encode}"
