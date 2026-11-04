"""Module « Services » de LIR.

Un client demande un service depuis la boutique (/boutique/services) :
  - « course » : un livreur achète (supermarché, marché…) ou gère une course, puis livre ;
  - « artisan » : un mécanicien, un électricien, un plombier… est contacté par LIR.
L'équipe traite les demandes dans le menu « Services » (/services) : elle confie la demande à un livreur
ou à un artisan, fixe les frais ou la commission, et peut transformer une course en livraison normale.

Ce fichier est indépendant d'app.py : wsgi.py l'importe après init_db(). Il ajoute ses propres tables
(services_cat, services_prestataires, services_demandes) sans toucher aux tables existantes.
"""
import re
import time
from urllib.parse import quote

from flask import abort, redirect, render_template_string, request, url_for

import app as A

app = A.app
log = A.log if hasattr(A, "log") else None

GENRES = {"course": "Course / achat par un livreur", "artisan": "Artisan / prestataire"}
STATUTS = ("nouvelle", "confirmée", "en cours", "terminée", "annulée")
STATUTS_ACTIFS = ("nouvelle", "confirmée", "en cours")
BOUTONS_STATUT = {"confirmée": "✅ Confirmer", "en cours": "▶️ En cours", "terminée": "🏁 Terminée", "annulée": "✖️ Annuler"}
PAIEMENTS_ACHATS = ("Le livreur avance l'argent, je rembourse à la livraison", "Je paie d'avance (mobile money)")
URGENCES = ("Aujourd'hui", "Cette semaine", "Pas urgent")

SERVICES_DEFAUT = (
    ("Courses et achats", "🛒", "course", "Un livreur achète ce que vous voulez (supermarché, marché, pharmacie…) et vous le livre à l'adresse indiquée.", 1),
    ("Faire une course ou une démarche", "📦", "course", "Un livreur gère une course ou un service à votre place : dépôt, retrait, paiement, remise d'un colis…", 2),
    ("Mécanicien", "🔧", "artisan", "Panne, entretien, dépannage : un mécanicien partenaire vous contacte.", 3),
    ("Électricien", "⚡", "artisan", "Installation, panne ou dépannage électrique à domicile.", 4),
    ("Plombier", "🚰", "artisan", "Fuite, installation, réparation de plomberie.", 5),
)


# ----------------------------------------------------------------------------- base de données
def init_services():
    with A.db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS services_cat (id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT NOT NULL, "
                    "emoji TEXT DEFAULT '🧰', genre TEXT NOT NULL DEFAULT 'course', description TEXT DEFAULT '', "
                    "frais_defaut INTEGER DEFAULT 0, actif INTEGER DEFAULT 1, ordre INTEGER DEFAULT 0)")
        con.execute("CREATE TABLE IF NOT EXISTS services_prestataires (id INTEGER PRIMARY KEY AUTOINCREMENT, service_id INTEGER, "
                    "nom TEXT NOT NULL, tel TEXT DEFAULT '', quartier TEXT DEFAULT '', tarif TEXT DEFAULT '', actif INTEGER DEFAULT 1)")
        con.execute("CREATE TABLE IF NOT EXISTS services_demandes (id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT, cree_le TEXT, "
                    "maj_le TEXT, service_id INTEGER, service_nom TEXT, emoji TEXT DEFAULT '🧰', genre TEXT, client_nom TEXT, "
                    "client_tel TEXT, quartier TEXT, adresse TEXT DEFAULT '', details TEXT, lieu_achat TEXT DEFAULT '', "
                    "budget INTEGER DEFAULT 0, paiement_achats TEXT DEFAULT '', urgence TEXT DEFAULT '', prestataire_pref INTEGER DEFAULT 0, "
                    "statut TEXT DEFAULT 'nouvelle', assigne_type TEXT DEFAULT '', assigne_id INTEGER DEFAULT 0, "
                    "assigne_nom TEXT DEFAULT '', frais INTEGER DEFAULT 0, note_interne TEXT DEFAULT '', livraison_id INTEGER DEFAULT 0)")
        if con.execute("SELECT COUNT(*) FROM services_cat").fetchone()[0] == 0:
            con.executemany("INSERT INTO services_cat(nom, emoji, genre, description, ordre) VALUES (?,?,?,?,?)", SERVICES_DEFAUT)


# ----------------------------------------------------------------------------- utilitaires
def _txt(nom, n):
    return request.form.get(nom, "").strip()[:n]


def _entier(valeur, maxi=999_999_999):
    chiffres = "".join(ch for ch in str(valeur or "") if ch.isdigit())[:9]
    return min(int(chiffres), maxi) if chiffres else 0


def _lien_wa(tel, texte):
    numero = A.tel_wa(tel)
    return f"https://wa.me/{numero}?text={quote(texte)}" if len(numero) >= 8 else ""


def _tel_entreprise():
    """Premier numéro de l'entreprise (le réglage peut en contenir plusieurs séparés par « / »)."""
    for morceau in str(A.entreprise_infos().get("tel", "")).split("/"):
        if len("".join(ch for ch in morceau if ch.isdigit())) >= 8:
            return morceau
    return ""


_DEMANDES_RECENTES = {}


def _trop_de_demandes(ip, maxi=6, fenetre=600):
    """Limite simple par adresse IP contre les envois en rafale (formulaire public)."""
    maintenant = time.time()
    horaires = [t for t in _DEMANDES_RECENTES.get(ip, []) if maintenant - t < fenetre]
    if len(horaires) >= maxi:
        _DEMANDES_RECENTES[ip] = horaires
        return True
    horaires.append(maintenant)
    _DEMANDES_RECENTES[ip] = horaires
    if len(_DEMANDES_RECENTES) > 2000:
        _DEMANDES_RECENTES.clear()
    return False


def _ip_client():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")


# ----------------------------------------------------------------------------- côté client (public)
STYLE_PUBLIC = """<style>
.svc label{display:block;font-size:.8rem;color:var(--mut);font-weight:650;margin:12px 0 4px}
.svc input,.svc select,.svc textarea{width:100%;padding:12px;border:1px solid var(--bord);border-radius:11px;font:inherit;background:var(--card);color:var(--txt)}
.svc textarea{min-height:110px;resize:vertical}.svc .hp{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}
.svc .choix{display:flex;gap:8px;align-items:center;padding:10px 12px;border:1px solid var(--bord);border-radius:11px;margin:6px 0;background:var(--card)}
.svc .choix input{width:auto}.svc .choix label{margin:0;color:var(--txt);font-size:.92rem;font-weight:600}
.svcmsg{background:rgba(240,165,0,.16);color:#7a5200;padding:10px 14px;border-radius:12px;margin-bottom:12px;font-weight:650}
</style>"""

PAGE_SERVICES_PUBLIC = ("""<!doctype html><html lang="fr"><head><title>{{ nom }} · Services</title>""" + A.SHOP_CSS + STYLE_PUBLIC + """</head><body>
<header class="hero"><div class="wrap"><div class="marque"><span class="t">🏍️ {{ nom }}</span><a href="{{ url_for('boutique') }}">← Boutique</a></div>
<h1 class="titre">Un service ?<br>On s'en occupe.</h1><p>Faire vos courses, gérer une démarche, trouver un mécanicien ou un électricien : décrivez votre besoin, nous vous répondons.</p></div></header>
<main class="wrap">
<section><div class="rayons">{% for s in services %}<a class="rayon" href="{{ url_for('svc_public_form', id=s.id) }}"><span class="ico">{{ s.emoji }}</span><b>{{ s.nom }}</b><small>{{ "Un livreur s'en charge" if s.genre == 'course' else 'Un artisan vous contacte' }}</small></a>
{% else %}<p class="vide" style="grid-column:1/-1">Les services arrivent bientôt.</p>{% endfor %}</div></section>
{% if wa %}<section><a class="btn sec" href="{{ wa }}" target="_blank" rel="noopener">💬 Nous écrire sur WhatsApp</a></section>{% endif %}
<p class="pied">{{ nom }} · livraison et services à domicile</p></main></body></html>""")

PAGE_SERVICE_FORM = ("""<!doctype html><html lang="fr"><head><title>{{ s.nom }} · {{ nom }}</title>""" + A.SHOP_CSS + STYLE_PUBLIC + """</head><body>
<header class="hero petit"><div class="wrap"><div class="marque"><span class="t">{{ s.emoji }} {{ s.nom }}</span><a href="{{ url_for('svc_public') }}">← Services</a></div>
<p style="margin-top:14px">{{ s.description }}</p></div></header>
<main class="wrap svc">
{% if msg %}<div class="svcmsg">{{ msg }}</div>{% endif %}
<form class="formcmd" method="post" action="{{ url_for('svc_public_envoi', id=s.id) }}">
<input class="hp" name="site_web" tabindex="-1" autocomplete="off" aria-hidden="true">
<label>Votre nom<input name="nom" required maxlength="100" autocomplete="name"></label>
<label>Votre téléphone (WhatsApp si possible)<input name="tel" type="tel" required maxlength="30" inputmode="tel" autocomplete="tel"></label>
<label>Quartier<input name="quartier" required maxlength="100"></label>
<label>{{ 'Adresse de livraison (repère, rue, porte…)' if s.genre == 'course' else 'Adresse où intervenir (repère, rue, porte…)' }}<input name="adresse" required maxlength="180"></label>
{% if s.genre == 'course' %}
<label>Que faut-il acheter ou faire ? (une ligne par article, avec les quantités)<textarea name="details" required maxlength="1500" placeholder="Ex. 1 bouteille de vin rouge, 2 kg de viande de bœuf, 3 tablettes de chocolat"></textarea></label>
<label>Où acheter ? (supermarché, marché… facultatif)<input name="lieu_achat" maxlength="150"></label>
<label>Budget estimé pour les achats en FCFA (facultatif)<input name="budget" type="number" min="0" step="1" inputmode="numeric"></label>
<label>Paiement des achats<select name="paiement_achats">{% for p in paiements %}<option>{{ p }}</option>{% endfor %}</select></label>
<p class="mut">Les frais de service vous sont annoncés avant que le livreur parte.</p>
{% else %}
<label>Décrivez le problème ou le besoin<textarea name="details" required maxlength="1500" placeholder="Ex. ma moto ne démarre plus, la prise du salon ne marche plus…"></textarea></label>
<label>C'est pour quand ?<select name="urgence">{% for u in urgences %}<option>{{ u }}</option>{% endfor %}</select></label>
{% if prestataires %}<label>Artisan souhaité (facultatif)</label>
<div class="choix"><input type="radio" name="prestataire" id="p0" value="0" checked><label for="p0">Peu importe, vous choisissez</label></div>
{% for p in prestataires %}<div class="choix"><input type="radio" name="prestataire" id="p{{ p.id }}" value="{{ p.id }}"><label for="p{{ p.id }}">{{ p.nom }}{% if p.quartier %} · {{ p.quartier }}{% endif %}{% if p.tarif %} · {{ p.tarif }}{% endif %}</label></div>{% endfor %}{% endif %}
<p class="mut">Nous vous mettons en relation avec l'artisan et le prix vous est précisé avant son intervention.</p>
{% endif %}
<p style="margin-top:16px"><button class="btn" type="submit">Envoyer ma demande</button></p></form>
<p class="pied">{{ nom }} · livraison et services à domicile</p></main></body></html>""")

PAGE_SERVICE_OK = ("""<!doctype html><html lang="fr"><head><title>Demande reçue · {{ nom }}</title>""" + A.SHOP_CSS + """</head><body>
<header class="hero petit"><div class="wrap"><div class="ident"><span class="logo-p">✅</span><h1 class="titre">Demande reçue</h1></div>
<p>Merci ! Votre demande{% if numero %} <b>{{ numero }}</b>{% endif %} est enregistrée.</p></div></header>
<main class="wrap"><section class="formcmd"><p>Notre équipe vous recontacte au téléphone que vous avez donné pour confirmer et vous annoncer le prix.</p>
<p><a class="btn" href="{{ url_for('svc_public') }}">Retour aux services</a> <a class="btn sec" href="{{ url_for('boutique') }}">Boutique</a></p></section>
<p class="pied">{{ nom }} · livraison et services à domicile</p></main></body></html>""")


def _service_actif(id):
    with A.db() as con:
        s = con.execute("SELECT * FROM services_cat WHERE id=? AND actif=1", (id,)).fetchone()
    if not s:
        abort(404)
    return s


@app.route("/boutique/services")
def svc_public():
    with A.db() as con:
        services = con.execute("SELECT * FROM services_cat WHERE actif=1 ORDER BY ordre, id").fetchall()
    tel = _tel_entreprise()
    wa = _lien_wa(tel, "Bonjour, j'ai besoin d'un service.") if tel else ""
    return A.reponse_portail(render_template_string(PAGE_SERVICES_PUBLIC, services=services, wa=wa, nom=A.nom_entreprise()))


@app.route("/boutique/services/<int:id>")
def svc_public_form(id):
    s = _service_actif(id)
    with A.db() as con:
        prestataires = con.execute("SELECT id, nom, quartier, tarif FROM services_prestataires WHERE service_id=? AND actif=1 "
                                   "ORDER BY nom COLLATE NOCASE", (id,)).fetchall() if s["genre"] == "artisan" else []
    return A.reponse_portail(render_template_string(PAGE_SERVICE_FORM, s=s, prestataires=prestataires, paiements=PAIEMENTS_ACHATS,
                                                    urgences=URGENCES, msg=request.args.get("msg", "")[:200], nom=A.nom_entreprise()))


@app.route("/boutique/services/<int:id>/demande", methods=["POST"])
def svc_public_envoi(id):
    s = _service_actif(id)
    if _txt("site_web", 100):  # champ piège rempli par les robots : on fait comme si tout allait bien
        return redirect(url_for("svc_public_ok"))
    nom, tel = _txt("nom", 100), A.chiffres(_txt("tel", 30))
    quartier, adresse, details = _txt("quartier", 100), _txt("adresse", 180), _txt("details", 1500)
    if len(nom) < 2 or len(tel) < 8 or not quartier or not adresse or len(details) < 5:
        return redirect(url_for("svc_public_form", id=id, msg="Indiquez votre nom, un téléphone valide (8 chiffres), votre quartier, l'adresse et le détail de la demande."))
    if _trop_de_demandes(_ip_client()):
        return "Trop de demandes envoyées en peu de temps. Réessayez dans quelques minutes.", 429
    course = s["genre"] == "course"
    paiement = request.form.get("paiement_achats", "")
    urgence = request.form.get("urgence", "")
    pref = _entier(request.form.get("prestataire", "0"))
    with A.db() as con:
        if pref and not con.execute("SELECT 1 FROM services_prestataires WHERE id=? AND service_id=? AND actif=1", (pref, id)).fetchone():
            pref = 0
        cur = con.execute(
            "INSERT INTO services_demandes(cree_le, maj_le, service_id, service_nom, emoji, genre, client_nom, client_tel, quartier, adresse, "
            "details, lieu_achat, budget, paiement_achats, urgence, prestataire_pref, frais) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (A.maintenant(), A.maintenant(), id, s["nom"], s["emoji"], s["genre"], nom, tel, quartier, adresse, details,
             _txt("lieu_achat", 150) if course else "", _entier(request.form.get("budget")) if course else 0,
             paiement if course and paiement in PAIEMENTS_ACHATS else "", urgence if not course and urgence in URGENCES else "",
             pref if not course else 0, s["frais_defaut"] or 0))
        numero = f"S-{cur.lastrowid:04d}"
        con.execute("UPDATE services_demandes SET numero=? WHERE id=?", (numero, cur.lastrowid))
    try:
        A.alerter_equipe(f"🆕 Demande de service {numero} : {s['nom']} · {nom} · {tel} · {quartier}. Ouvrez « Services » dans l'application.")
    except Exception:
        if log:
            log.exception("Alerte équipe non envoyée pour la demande %s", numero)
    return redirect(url_for("svc_public_ok", n=numero))


@app.route("/boutique/services/envoyee")
def svc_public_ok():
    numero = request.args.get("n", "")[:12]
    numero = numero if re.fullmatch(r"S-\d{1,8}", numero) else ""
    return A.reponse_portail(render_template_string(PAGE_SERVICE_OK, numero=numero, nom=A.nom_entreprise()))


# ----------------------------------------------------------------------------- côté équipe (administration)
PAGE_SERVICES_ADMIN = A.BASE.replace("{% block corps %}{% endblock %}", """
<div class="entete"><div><h1>🧰 Services</h1><p>Demandes reçues : courses et achats par un livreur, artisans (mécanicien, électricien…).</p></div>
<a class="btn sec" href="{{ url_for('svc_catalogue') }}">⚙️ Gérer services et artisans</a></div>
{% if msg %}<div class="card"><span class="pastille">{{ msg }}</span></div>{% endif %}
<div class="stats" style="margin-bottom:18px">
<div class="stat ambre"><b>{{ st.nouvelles }}</b><span>nouvelle(s) demande(s)</span></div>
<div class="stat"><b>{{ st.en_cours }}</b><span>confirmée(s) ou en cours</span></div>
<div class="stat"><b>{{ st.terminees }}</b><span>terminée(s) ce mois</span></div>
<div class="stat"><b>{{ st.frais|fcfa }} F</b><span>frais et commissions du mois</span></div></div>
<div class="card" style="display:flex;gap:8px;flex-wrap:wrap">
{% for cle, nom in filtres %}<a class="btn {{ '' if cle == filtre else 'sec' }}" href="{{ url_for('svc_admin', statut=cle) }}">{{ nom }}</a>{% endfor %}</div>
{% for d in demandes %}<div class="card" id="d{{ d.id }}">
<div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h2 style="margin:0">{{ d.emoji }} {{ d.numero }} · {{ d.service_nom }}</h2>
<span class="pastille {{ 'rouge' if d.statut == 'annulée' else ('ambre' if d.statut == 'nouvelle' else '') }}">{{ d.statut }}</span></div>
<p class="mut">{{ d.cree_le }} · {{ d.client_nom }} · {{ d.client_tel }} · {{ d.quartier }}{% if d.adresse %} · {{ d.adresse }}{% endif %}</p>
<p style="white-space:pre-wrap">{{ d.details }}</p>
{% if d.genre == 'course' %}<p class="mut">{% if d.lieu_achat %}Lieu d'achat : {{ d.lieu_achat }} · {% endif %}Budget : {{ d.budget|fcfa }} F{% if d.paiement_achats %} · {{ d.paiement_achats }}{% endif %}</p>
{% else %}<p class="mut">Urgence : {{ d.urgence or '—' }}{% if d.pref_nom %} · Artisan souhaité : {{ d.pref_nom }}{% endif %}</p>{% endif %}
<form method="post" action="{{ url_for('svc_maj', id=d.id) }}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;align-items:end">
<label>Confié à<select name="assigne"><option value="">— personne —</option>{% for o in d.options %}<option value="{{ o.val }}" {{ 'selected' if o.val == d.assigne_val }}>{{ o.nom }}</option>{% endfor %}</select></label>
<label>{{ 'Frais de service (FCFA)' if d.genre == 'course' else 'Commission (FCFA)' }}<input name="frais" type="number" min="0" step="1" value="{{ d.frais }}"></label>
<label>Note interne<input name="note" maxlength="300" value="{{ d.note_interne }}"></label>
<div style="display:flex;gap:6px;flex-wrap:wrap;grid-column:1/-1"><button name="action" value="enregistrer">Enregistrer</button>
{% for s in ('confirmée', 'en cours', 'terminée', 'annulée') %}{% if s != d.statut %}<button class="sec" name="statut" value="{{ s }}">{{ boutons[s] }}</button>{% endif %}{% endfor %}
{% if d.genre == 'course' and not d.livraison_id %}<button class="sec" name="action" value="livraison">🚚 Créer la livraison</button>{% endif %}</div></form>
<p style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
{% if d.livraison_id %}<a class="btn sec" href="/modifier/{{ d.livraison_id }}">🚚 Ouvrir la livraison liée</a>{% endif %}
{% if d.wa_client %}<a class="btn sec" href="{{ d.wa_client }}" target="_blank" rel="noopener">💬 Écrire au client</a>{% endif %}
{% if d.wa_assigne %}<a class="btn sec" href="{{ d.wa_assigne }}" target="_blank" rel="noopener">📤 Envoyer à {{ d.assigne_nom }}</a>{% endif %}</p></div>
{% else %}<div class="card"><p class="vide">Aucune demande dans cette liste. Les demandes arrivent depuis la boutique : <b>/boutique/services</b>.</p></div>{% endfor %}
""")

PAGE_CATALOGUE_ADMIN = A.BASE.replace("{% block corps %}{% endblock %}", """
<div class="entete"><div><h1>⚙️ Services et artisans</h1><p>Choisissez les services proposés aux clients et la liste de vos artisans partenaires.</p></div>
<a class="btn sec" href="{{ url_for('svc_admin') }}">← Demandes</a></div>
{% if msg %}<div class="card"><span class="pastille {{ 'rouge' if erreur else '' }}">{{ msg }}</span></div>{% endif %}
<div class="card"><h2>Services proposés</h2>
{% for s in services %}<form method="post" action="{{ url_for('svc_cat_service') }}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;align-items:end;border-bottom:1px solid var(--bord);padding:10px 0">
<input type="hidden" name="id" value="{{ s.id }}">
<label>Nom<input name="nom" value="{{ s.nom }}" required maxlength="80"></label>
<label>Icône<input name="emoji" value="{{ s.emoji }}" maxlength="8"></label>
<label>Type<select name="genre">{% for k, v in genres.items() %}<option value="{{ k }}" {{ 'selected' if k == s.genre }}>{{ v }}</option>{% endfor %}</select></label>
<label>Frais de départ (FCFA)<input name="frais_defaut" type="number" min="0" step="1" value="{{ s.frais_defaut }}"></label>
<label>Ordre<input name="ordre" type="number" min="0" step="1" value="{{ s.ordre }}"></label>
<label style="grid-column:1/-1">Description montrée aux clients<input name="description" value="{{ s.description }}" maxlength="300"></label>
<label><span><input type="checkbox" name="actif" {{ 'checked' if s.actif }}> Visible par les clients</span></label><button>Enregistrer</button></form>{% endfor %}
<h2 style="margin-top:18px">➕ Nouveau service</h2>
<form method="post" action="{{ url_for('svc_cat_service') }}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;align-items:end">
<label>Nom<input name="nom" required maxlength="80" placeholder="Ex. Coiffeur à domicile"></label><label>Icône<input name="emoji" value="🧰" maxlength="8"></label>
<label>Type<select name="genre">{% for k, v in genres.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select></label>
<label>Frais de départ (FCFA)<input name="frais_defaut" type="number" min="0" step="1" value="0"></label>
<label style="grid-column:1/-1">Description montrée aux clients<input name="description" maxlength="300"></label>
<input type="hidden" name="actif" value="on"><button>Ajouter</button></form></div>
<div class="card"><h2>Artisans partenaires</h2><p class="mut">Seuls les services de type « artisan » proposent des artisans. Leur numéro n'est jamais montré aux clients : c'est l'équipe qui fait la mise en relation.</p>
{% for p in prestataires %}<form method="post" action="{{ url_for('svc_cat_prestataire') }}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;align-items:end;border-bottom:1px solid var(--bord);padding:10px 0">
<input type="hidden" name="id" value="{{ p.id }}">
<label>Nom<input name="nom" value="{{ p.nom }}" required maxlength="100"></label><label>Téléphone<input name="tel" value="{{ p.tel }}" maxlength="30"></label>
<label>Service<select name="service_id">{% for s in artisans %}<option value="{{ s.id }}" {{ 'selected' if s.id == p.service_id }}>{{ s.nom }}</option>{% endfor %}</select></label>
<label>Quartier<input name="quartier" value="{{ p.quartier }}" maxlength="100"></label><label>Tarif indicatif<input name="tarif" value="{{ p.tarif }}" maxlength="100"></label>
<label><span><input type="checkbox" name="actif" {{ 'checked' if p.actif }}> Actif</span></label><button>Enregistrer</button></form>
{% else %}<p class="vide">Aucun artisan pour le moment.</p>{% endfor %}
{% if artisans %}<h2 style="margin-top:18px">➕ Nouvel artisan</h2>
<form method="post" action="{{ url_for('svc_cat_prestataire') }}" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;align-items:end">
<label>Nom<input name="nom" required maxlength="100"></label><label>Téléphone<input name="tel" required maxlength="30"></label>
<label>Service<select name="service_id">{% for s in artisans %}<option value="{{ s.id }}">{{ s.nom }}</option>{% endfor %}</select></label>
<label>Quartier<input name="quartier" maxlength="100"></label><label>Tarif indicatif<input name="tarif" maxlength="100" placeholder="Ex. dès 3 000 F"></label>
<input type="hidden" name="actif" value="on"><button>Ajouter</button></form>{% else %}<p class="mut">Ajoutez d'abord un service de type « artisan » pour pouvoir y rattacher des artisans.</p>{% endif %}</div>
""")


def _texte_assigne(d):
    if d["genre"] == "course":
        lignes = [f"Nouvelle course {d['numero']} ({A.nom_entreprise()})", f"À faire : {d['details']}"]
        if d["lieu_achat"]:
            lignes.append(f"Où acheter : {d['lieu_achat']}")
        if d["budget"]:
            lignes.append(f"Budget : {d['budget']} F")
        if d["paiement_achats"]:
            lignes.append(f"Paiement des achats : {d['paiement_achats']}")
        lignes.append(f"Livrer à : {d['quartier']} · {d['adresse']}")
    else:
        lignes = [f"Nouvelle demande {d['numero']} : {d['service_nom']} ({A.nom_entreprise()})", f"Besoin : {d['details']}"]
        if d["urgence"]:
            lignes.append(f"Pour : {d['urgence']}")
        lignes.append(f"Lieu : {d['quartier']} · {d['adresse']}")
    lignes.append(f"Client : {d['client_nom']} · {d['client_tel']}")
    return "\n".join(lignes)


@app.route("/services")
def svc_admin():
    filtre = request.args.get("statut", "actives")
    filtres = [("actives", "À traiter")] + [(s, s.capitalize()) for s in STATUTS] + [("toutes", "Toutes")]
    if filtre not in {k for k, _ in filtres}:
        filtre = "actives"
    mois = A.maintenant()[:7]
    with A.db() as con:
        if filtre == "toutes":
            lignes = con.execute("SELECT * FROM services_demandes ORDER BY id DESC LIMIT 200").fetchall()
        elif filtre == "actives":
            lignes = con.execute("SELECT * FROM services_demandes WHERE statut IN ('nouvelle','confirmée','en cours') "
                                 "ORDER BY CASE statut WHEN 'nouvelle' THEN 0 WHEN 'confirmée' THEN 1 ELSE 2 END, id DESC LIMIT 200").fetchall()
        else:
            lignes = con.execute("SELECT * FROM services_demandes WHERE statut=? ORDER BY id DESC LIMIT 200", (filtre,)).fetchall()
        livreurs = con.execute("SELECT id, nom, tel FROM livreurs WHERE actif=1 ORDER BY nom COLLATE NOCASE").fetchall()
        prestataires = con.execute("SELECT id, service_id, nom, tel, quartier FROM services_prestataires WHERE actif=1 "
                                   "ORDER BY nom COLLATE NOCASE").fetchall()
        tous_prest = {r["id"]: r for r in con.execute("SELECT id, nom, tel FROM services_prestataires")}
        tous_liv = {r["id"]: r for r in con.execute("SELECT id, nom, tel FROM livreurs")}
        st = {"nouvelles": con.execute("SELECT COUNT(*) FROM services_demandes WHERE statut='nouvelle'").fetchone()[0],
              "en_cours": con.execute("SELECT COUNT(*) FROM services_demandes WHERE statut IN ('confirmée','en cours')").fetchone()[0],
              "terminees": con.execute("SELECT COUNT(*) FROM services_demandes WHERE statut='terminée' AND substr(maj_le,1,7)=?", (mois,)).fetchone()[0],
              "frais": con.execute("SELECT COALESCE(SUM(frais),0) FROM services_demandes WHERE statut='terminée' AND substr(maj_le,1,7)=?", (mois,)).fetchone()[0]}
    demandes = []
    for r in lignes:
        d = dict(r)
        if d["genre"] == "course":
            d["options"] = [{"val": f"livreur:{x['id']}", "nom": f"🏍️ {x['nom']}"} for x in livreurs]
        else:
            d["options"] = [{"val": f"prestataire:{x['id']}", "nom": f"🛠️ {x['nom']}" + (f" · {x['quartier']}" if x["quartier"] else "")}
                            for x in prestataires if x["service_id"] == d["service_id"]]
        d["assigne_val"] = f"{d['assigne_type']}:{d['assigne_id']}" if d["assigne_type"] else ""
        if d["assigne_val"] and d["assigne_val"] not in {o["val"] for o in d["options"]}:  # personne déjà désignée mais devenue inactive
            d["options"].append({"val": d["assigne_val"], "nom": d["assigne_nom"] or "(ancien)"})
        pref = tous_prest.get(d["prestataire_pref"])
        d["pref_nom"] = pref["nom"] if pref else ""
        d["wa_client"] = _lien_wa(d["client_tel"], f"Bonjour {d['client_nom']}, c'est {A.nom_entreprise()} au sujet de votre demande {d['numero']} ({d['service_nom']}).")
        cible = (tous_liv if d["assigne_type"] == "livreur" else tous_prest).get(d["assigne_id"])
        d["wa_assigne"] = _lien_wa(cible["tel"], _texte_assigne(d)) if cible and d["assigne_nom"] else ""
        demandes.append(d)
    return render_template_string(PAGE_SERVICES_ADMIN, demandes=demandes, st=st, filtres=filtres, filtre=filtre,
                                  boutons=BOUTONS_STATUT, msg=request.args.get("msg", "")[:200])


def _creer_livraison(con, d):
    """Transforme une demande « course » en livraison classique (suivi, revenus, carburant…)."""
    colis = d["details"]
    cur = con.execute(
        "INSERT INTO livraisons(canal, client_nom, client_tel, collecte_lieu, collecte_quartier, livraison_adresse, livraison_quartier, "
        "destinataire_nom, destinataire_tel, colis, valeur_produit, prix_course, mode_paiement, statut_paiement, statut, remarques, "
        "message_original, cree_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("Services", d["client_nom"], d["client_tel"], d["lieu_achat"] or "Achats à faire (lieu à préciser)", "", d["adresse"], d["quartier"],
         d["client_nom"], d["client_tel"], colis, d["budget"] or 0, d["frais"] or 0, "Espèces", "en attente", "en attente",
         (d["paiement_achats"] or "Achats à avancer par le livreur") + f" · demande {d['numero']}",
         f"Service {d['numero']} ({d['service_nom']}) : {d['details']}", A.maintenant()))
    lid = cur.lastrowid
    con.execute("UPDATE livraisons SET numero=? WHERE id=?", (f"LIV-{lid:04d}", lid))
    if d["assigne_type"] == "livreur" and d["assigne_nom"]:
        con.execute("UPDATE livraisons SET livreur=? WHERE id=?", (d["assigne_nom"], lid))
    return lid


@app.route("/services/demande/<int:id>", methods=["POST"])
def svc_maj(id):
    with A.db() as con:
        d = con.execute("SELECT * FROM services_demandes WHERE id=?", (id,)).fetchone()
        if not d:
            abort(404)
        d = dict(d)
        d["frais"] = _entier(request.form.get("frais"))
        d["note_interne"] = _txt("note", 300)
        choix = request.form.get("assigne", "")
        if not choix:
            d["assigne_type"], d["assigne_id"], d["assigne_nom"] = "", 0, ""
        else:
            genre, _, ident = choix.partition(":")
            ident = _entier(ident)
            table = {"livreur": "livreurs", "prestataire": "services_prestataires"}.get(genre)
            ligne = con.execute(f"SELECT nom FROM {table} WHERE id=?", (ident,)).fetchone() if table else None
            if not ligne:
                return redirect(url_for("svc_admin", msg="Personne introuvable : la demande n'a pas été modifiée."))
            if not (genre == d["assigne_type"] and ident == d["assigne_id"]):
                d["assigne_type"], d["assigne_id"], d["assigne_nom"] = genre, ident, ligne["nom"]
        statut = request.form.get("statut", "")
        if statut in STATUTS:
            d["statut"] = statut
        elif d["assigne_id"] and d["statut"] == "nouvelle":
            d["statut"] = "confirmée"
        msg = "Demande enregistrée."
        if request.form.get("action") == "livraison" and d["genre"] == "course" and not d["livraison_id"]:
            d["livraison_id"] = _creer_livraison(con, d)
            if d["statut"] in ("nouvelle", "confirmée"):
                d["statut"] = "en cours"
            msg = "Livraison créée : elle apparaît dans les livraisons."
        con.execute("UPDATE services_demandes SET assigne_type=?, assigne_id=?, assigne_nom=?, frais=?, note_interne=?, statut=?, "
                    "livraison_id=?, maj_le=? WHERE id=?",
                    (d["assigne_type"], d["assigne_id"], d["assigne_nom"], d["frais"], d["note_interne"], d["statut"],
                     d["livraison_id"], A.maintenant(), id))
    return redirect(url_for("svc_admin", statut=request.args.get("statut", "actives"), msg=msg) + f"#d{id}")


@app.route("/services/catalogue")
def svc_catalogue():
    with A.db() as con:
        services = con.execute("SELECT * FROM services_cat ORDER BY ordre, id").fetchall()
        prestataires = con.execute("SELECT * FROM services_prestataires ORDER BY actif DESC, nom COLLATE NOCASE").fetchall()
    return render_template_string(PAGE_CATALOGUE_ADMIN, services=services, prestataires=prestataires, genres=GENRES,
                                  artisans=[s for s in services if s["genre"] == "artisan"],
                                  msg=request.args.get("msg", "")[:200], erreur=request.args.get("erreur", "") == "1")


@app.route("/services/catalogue/service", methods=["POST"])
def svc_cat_service():
    id_ = _entier(request.form.get("id"))
    nom, genre = _txt("nom", 80), request.form.get("genre", "")
    if not nom or genre not in GENRES:
        return redirect(url_for("svc_catalogue", erreur=1, msg="Indiquez un nom et un type de service."))
    valeurs = (nom, _txt("emoji", 8) or "🧰", genre, _txt("description", 300), _entier(request.form.get("frais_defaut")),
               1 if request.form.get("actif") else 0, _entier(request.form.get("ordre")))
    with A.db() as con:
        if id_:
            con.execute("UPDATE services_cat SET nom=?, emoji=?, genre=?, description=?, frais_defaut=?, actif=?, ordre=? WHERE id=?", valeurs + (id_,))
        else:
            con.execute("INSERT INTO services_cat(nom, emoji, genre, description, frais_defaut, actif, ordre) VALUES (?,?,?,?,?,?,?)",
                        valeurs[:-1] + (valeurs[-1] or 99,))
    return redirect(url_for("svc_catalogue", msg="Service enregistré."))


@app.route("/services/catalogue/prestataire", methods=["POST"])
def svc_cat_prestataire():
    id_ = _entier(request.form.get("id"))
    nom, service_id = _txt("nom", 100), _entier(request.form.get("service_id"))
    with A.db() as con:
        service = con.execute("SELECT 1 FROM services_cat WHERE id=? AND genre='artisan'", (service_id,)).fetchone()
        if not nom or not service:
            return redirect(url_for("svc_catalogue", erreur=1, msg="Indiquez un nom et un service de type artisan."))
        valeurs = (service_id, nom, _txt("tel", 30), _txt("quartier", 100), _txt("tarif", 100), 1 if request.form.get("actif") else 0)
        if id_:
            con.execute("UPDATE services_prestataires SET service_id=?, nom=?, tel=?, quartier=?, tarif=?, actif=? WHERE id=?", valeurs + (id_,))
        else:
            con.execute("INSERT INTO services_prestataires(service_id, nom, tel, quartier, tarif, actif) VALUES (?,?,?,?,?,?)", valeurs)
    return redirect(url_for("svc_catalogue", msg="Artisan enregistré."))


# ----------------------------------------------------------------------------- liens dans les pages existantes
_ANCRE_REVENUS = re.compile(r'<a\b[^>]*\bhref="/revenus"[^>]*>.*?</a>', re.S)


def _ancre_services(ancre, actif):
    ouverture, fin = ancre.split(">", 1)
    ouverture = ouverture.replace('href="/revenus"', 'href="/services"')
    ouverture = re.sub(r'class="([^"]*)"', lambda m: 'class="' + " ".join(c for c in m.group(1).split() if c != "on") + (" on" if actif else "") + '"', ouverture)
    return ouverture + ">" + fin.replace("💰", "🧰").replace("Revenus", "Services")


@app.after_request
def injecter_liens_services(reponse):
    """Ajoute « Services » au menu de l'administration et une bande d'accès sur la boutique, sans modifier app.py."""
    try:
        if reponse.status_code != 200 or reponse.mimetype != "text/html" or reponse.direct_passthrough:
            return reponse
        chemin = request.path
        corps = reponse.get_data(as_text=True)
        if chemin == "/boutique":
            with A.db() as con:
                if not con.execute("SELECT 1 FROM services_cat WHERE actif=1 LIMIT 1").fetchone():
                    return reponse
            bande = ('<section style="margin-top:6px"><a href="/boutique/services" style="display:flex;gap:14px;align-items:center;text-decoration:none;'
                     'background:linear-gradient(135deg,#f0a500,#c27c00);color:#2b1d00;border-radius:20px;padding:16px;box-shadow:var(--ombre)">'
                     '<span style="font-size:2rem">🧰</span><span><b style="display:block;font-size:1.05rem">Besoin d\'un service ?</b>'
                     '<span>Courses et achats, mécanicien, électricien… demandez-le ici.</span></span></a></section>')
            nouveau = corps.replace('<main class="wrap">', '<main class="wrap">' + bande, 1)
        elif not A.chemin_public(chemin):
            actif = chemin.startswith("/services")
            nouveau = _ANCRE_REVENUS.sub(lambda m: m.group(0) + _ancre_services(m.group(0), actif) if "Revenus" in m.group(0) else m.group(0), corps)
        else:
            return reponse
        if nouveau != corps:
            reponse.set_data(nouveau)
    except Exception:
        if log:
            log.exception("Injection des liens Services impossible")
    return reponse


init_services()
