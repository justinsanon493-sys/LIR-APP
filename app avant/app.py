"""
Base de données de livraisons — application locale.

Lancer :  python app.py
Ouvrir :  http://localhost:5000
Base   :  livraisons.db (créée automatiquement à côté de ce fichier)
"""
import csv
import io
import json
import os
import sqlite3
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, render_template_string, request, url_for

DOSSIER = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(DOSSIER, "livraisons.db")
MODELE = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

app = Flask(__name__)

# (clé, libellé, type, options)
CHAMPS = [
    ("canal", "Canal de la commande", "select", ["WhatsApp", "Appel", "En personne"]),
    ("client_nom", "Nom du client", "text", None),
    ("client_tel", "Téléphone du client", "text", None),
    ("collecte_lieu", "Lieu de collecte", "text", None),
    ("collecte_quartier", "Quartier de collecte", "text", None),
    ("livraison_adresse", "Adresse / repère de livraison", "text", None),
    ("livraison_quartier", "Quartier de livraison", "text", None),
    ("destinataire_nom", "Nom du destinataire", "text", None),
    ("destinataire_tel", "Téléphone du destinataire", "text", None),
    ("colis", "Description du colis", "text", None),
    ("valeur_produit", "Valeur du produit (FCFA)", "number", None),
    ("prix_course", "Prix de la course (FCFA)", "number", None),
    ("mode_paiement", "Mode de paiement", "select", ["Espèces", "Orange Money", "Mobi Cash"]),
    ("statut_paiement", "Statut du paiement", "select", ["en attente", "payé", "crédit"]),
    ("frais", "Frais engagés (carburant, etc.)", "number", None),
    ("distance_km", "Distance (km)", "number", None),
    ("statut", "Statut de la livraison", "select",
     ["en attente", "collecté", "livré", "annulé", "injoignable", "reporté"]),
    ("remarques", "Remarques / problèmes", "textarea", None),
]
CHAMPS[10:10] = [
    ("categorie", "Catégorie du produit", "select",
     ["", "Alimentation", "Médicaments / pharmacie", "Vêtements", "Électronique", "Documents",
      "Boissons", "Cosmétiques", "Quincaillerie", "Autre"]),
    ("produit", "Produit précis (ex : poulet, paracétamol)", "text", None),
    ("quantite", "Quantité", "number", None),
]
CHAMPS[3:3] = [
    ("type_client", "Type de client", "select",
     ["", "Particulier", "Commerçant", "Restaurant", "Pharmacie", "Entreprise", "Autre"]),
    ("client_quartier", "Quartier de résidence du client", "text", None),
    ("source_client", "Comment le client nous a connus", "select",
     ["", "Bouche-à-oreille", "WhatsApp", "Flyer", "Réseaux sociaux", "Autre"]),
]
CLES = [c[0] for c in CHAMPS]
NOMBRES = {"valeur_produit", "prix_course", "frais", "distance_km", "quantite"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS livraisons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  numero TEXT,
  cree_le TEXT,
  canal TEXT, client_nom TEXT, client_tel TEXT,
  collecte_lieu TEXT, collecte_quartier TEXT,
  livraison_adresse TEXT, livraison_quartier TEXT,
  destinataire_nom TEXT, destinataire_tel TEXT,
  colis TEXT, valeur_produit REAL DEFAULT 0,
  prix_course REAL DEFAULT 0, mode_paiement TEXT,
  statut_paiement TEXT DEFAULT 'en attente',
  frais REAL DEFAULT 0, distance_km REAL,
  statut TEXT DEFAULT 'en attente',
  heure_collecte TEXT, heure_livraison TEXT, heure_paiement TEXT,
  remarques TEXT, message_original TEXT
);
"""


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript(SCHEMA + EXTRA)
        migrer(con)


def maintenant():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def nombre(valeur):
    try:
        return float(str(valeur).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return 0 if valeur in ("", None) else None


def lire_formulaire():
    donnees = {}
    for cle in CLES:
        v = request.form.get(cle, "").strip()
        if cle in NOMBRES:
            donnees[cle] = nombre(v) if v else (None if cle == "distance_km" else 0)
        else:
            donnees[cle] = v
    donnees["message_original"] = request.form.get("message_original", "")
    for t in ("client_tel", "destinataire_tel"):  # numéros sans espaces : un client = un numéro
        donnees[t] = chiffres(donnees[t])
    return donnees


# ---------------------------------------------------------------- Claude
PROMPT_SYSTEME = (
    "Tu extrais les informations d'une commande de livraison à moto à Ouagadougou "
    "(Burkina Faso) depuis un message client. Le message peut être en français, "
    "avec du mooré ou du dioula. Réponds UNIQUEMENT par un objet JSON, sans texte "
    "autour, avec exactement ces clés : "
    + ", ".join(CLES)
    + ". Règles : valeur \"\" si l'information n'est pas dans le message, ne devine "
    "jamais ; montants en FCFA, nombres sans espace ni symbole ; "
    "canal = \"WhatsApp\" par défaut ; mode_paiement parmi Espèces, Orange Money, "
    "Mobi Cash ; statut = \"en attente\" ; statut_paiement = \"en attente\" ; "
    "garde les noms de quartiers et de lieux tels qu'écrits par le client. "
    "categorie parmi : Alimentation, Médicaments / pharmacie, Vêtements, Électronique, Documents, "
    "Boissons, Cosmétiques, Quincaillerie, Autre ; produit = le produit principal demandé "
    "(ex. poulet, paracétamol) ; quantite = nombre d'unités ; type_client parmi Particulier, "
    "Commerçant, Restaurant, Pharmacie, Entreprise, Autre (seulement si c'est évident) ; "
    "source_client et client_quartier : vide sauf si le message le dit."
)


def extraire_avec_claude(message):
    import anthropic  # importé ici pour que l'app démarre même sans la bibliothèque

    client = anthropic.Anthropic()  # lit la variable ANTHROPIC_API_KEY
    rep = client.messages.create(
        model=MODELE,
        max_tokens=800,
        system=PROMPT_SYSTEME,
        messages=[{"role": "user", "content": message}],
    )
    texte = "".join(b.text for b in rep.content if getattr(b, "type", "") == "text")
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("Réponse de Claude illisible")
    brut = json.loads(texte[debut:fin + 1])
    return {k: ("" if brut.get(k) is None else brut.get(k)) for k in CLES}


# ---------------------------------------------------------------- Pages
BASE = """
<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mes livraisons</title>
<style>
:root{--bg:#f2f5f3;--card:#fff;--txt:#14201a;--mut:#69786f;--vert:#0a7d3c;--rouge:#d64545;--bord:#e3e9e5;--soft:rgba(10,125,60,.08);--ombre:0 4px 18px rgba(10,60,30,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#0d1411;--card:#16201b;--txt:#e7efe9;--mut:#8ca096;--bord:#24322a;--soft:rgba(46,204,113,.1);--ombre:none}}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--txt)}
nav{position:sticky;top:0;z-index:5;background:linear-gradient(135deg,#0a7d3c,#07521f);padding:10px 16px;display:flex;gap:6px;align-items:center;overflow-x:auto;white-space:nowrap;box-shadow:0 2px 12px rgba(0,0,0,.2)}
nav .brand{color:#fff;font-weight:800;margin-right:10px;font-size:1.1rem}
nav a{color:#e8f7ee;text-decoration:none;font-weight:600;padding:7px 12px;border-radius:999px;font-size:.92rem}
nav a:hover{background:rgba(255,255,255,.18)}
main{max-width:1080px;margin:0 auto;padding:18px 14px 40px}
.card{background:var(--card);border:1px solid var(--bord);border-radius:16px;padding:16px;margin-bottom:16px;box-shadow:var(--ombre)}
h2{margin:0 0 12px;font-size:1.05rem}a{color:var(--vert)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{background:var(--soft);border-radius:12px;padding:12px 14px}
.stat b{display:block;font-size:1.45rem}.stat span{color:var(--mut);font-size:.82rem}
label{display:block;font-size:.82rem;color:var(--mut);margin:10px 0 4px;font-weight:600}
input,select,textarea{width:100%;padding:11px;border:1px solid var(--bord);border-radius:10px;font-size:1rem;font-family:inherit;background:var(--card);color:var(--txt)}
input:focus,select:focus,textarea:focus{outline:2px solid var(--vert);border-color:transparent}
button,.btn{background:var(--vert);color:#fff;border:0;border-radius:999px;padding:9px 16px;font-size:.92rem;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{filter:brightness(1.1)}
button.sec,.btn.sec{background:transparent;color:var(--vert);border:1px solid var(--vert)}
.grille{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:0 16px}
table{width:100%;border-collapse:collapse;font-size:.9rem}th,td{padding:10px 6px;border-bottom:1px solid var(--bord);text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:.8rem;text-transform:uppercase}
.scroll{overflow-x:auto}.chart{position:relative;height:260px}
.tag{padding:3px 10px;border-radius:999px;font-size:.76rem;font-weight:600;background:var(--soft);color:var(--mut)}
.livré,.payé{background:rgba(10,125,60,.15);color:var(--vert)}.annulé,.injoignable{background:rgba(214,69,69,.15);color:var(--rouge)}.collecté{background:rgba(242,169,0,.18);color:#b07800}
.ligne{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--bord)}
form.inline{display:inline}.mut{color:var(--mut);font-size:.85rem}
.nsearch{margin-left:auto}.nsearch input{padding:7px 14px;border-radius:999px;border:0;min-width:190px;font-size:.9rem}
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script></head><body>
<nav><span class="brand">🏍️ LIR</span><a href="{{ url_for('accueil') }}">Tableau de bord</a>
<a href="{{ url_for('nouvelle') }}">+ Nouvelle</a>
<a href="{{ url_for('toutes') }}">Livraisons</a>
<a href="{{ url_for('clients') }}">Clients</a>
<a href="{{ url_for('marche') }}">Marché</a>
<a href="{{ url_for('stats') }}">Statistiques</a>
<a href="{{ url_for('export') }}">Export CSV</a>
<form method="get" action="{{ url_for('recherche') }}" class="nsearch"><input name="q" placeholder="🔍 Nom, numéro, produit…" required></form></nav>
<main>{% block corps %}{% endblock %}</main></body></html>
"""

PAGE_ACCUEIL = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>Aujourd'hui</h2><div class="stats">
 <div class="stat"><b>{{ jour.n }}</b><span>livraisons</span></div>
 <div class="stat"><b>{{ '{:,.0f}'.format(jour.revenu).replace(',', ' ') }}</b><span>FCFA de courses</span></div>
 <div class="stat"><b>{{ '{:,.0f}'.format(jour.frais).replace(',', ' ') }}</b><span>FCFA de frais</span></div>
 <div class="stat"><b>{{ '{:,.0f}'.format(jour.revenu - jour.frais).replace(',', ' ') }}</b><span>FCFA de bénéfice</span></div>
</div></div>
<div class="card"><h2>Total depuis le début</h2><div class="stats">
 <div class="stat"><b>{{ total.n }}</b><span>livraisons</span></div>
 <div class="stat"><b>{{ '{:,.0f}'.format(total.revenu).replace(',', ' ') }}</b><span>FCFA de courses</span></div>
 <div class="stat"><b>{{ '{:,.0f}'.format(impayes).replace(',', ' ') }}</b><span>FCFA à encaisser</span></div>
</div></div>
<div class="card"><h2>En cours</h2>
{% if en_cours %}{% include_rows %}{% else %}<p class="mut">Aucune livraison en cours.</p>{% endif %}</div>
<div class="grille">
<div class="card"><h2>📈 7 derniers jours</h2><div class="chart"><canvas id="c7"></canvas></div></div>
<div class="card"><h2>🔔 À relancer ({{ relances|length }})</h2>
{% for r in relances %}<div class="ligne"><div><b>{{ r.client_nom or r.client_tel or 'Client' }}</b><br><span class="mut">{{ r.numero }} · {{ r.jours }} j · {{ r.prix_course|fcfa }} F</span></div>
{% if lien_relance(r) %}<a class="btn" target="_blank" href="{{ lien_relance(r) }}">Relancer</a>{% endif %}</div>
{% else %}<p class="mut">Aucun impayé 👏</p>{% endfor %}</div>
</div>
<script>
if(window.Chart){const s={{ serie|tojson }};
new Chart(document.getElementById('c7'),{type:'bar',data:{labels:s.labels,datasets:[{label:'Revenus',data:s.revenus,backgroundColor:'#0a7d3c',borderRadius:6},{label:'Bénéfice',data:s.benefices,backgroundColor:'#9bd8b4',borderRadius:6}]},options:{maintainAspectRatio:false,plugins:{legend:{position:'bottom'}}}});}
</script>
<div class="grille">
<div class="card"><h2>Meilleurs clients</h2><table>
{% for c in clients %}<tr><td>{{ c.client_nom }}</td><td>{{ c.n }} courses</td><td>{{ '{:,.0f}'.format(c.total).replace(',', ' ') }} F</td></tr>
{% else %}<tr><td class="mut">Pas encore de données</td></tr>{% endfor %}</table></div>
<div class="card"><h2>Quartiers les plus livrés</h2><table>
{% for q in quartiers %}<tr><td>{{ q.livraison_quartier }}</td><td>{{ q.n }} courses</td><td>{{ '{:,.0f}'.format(q.total).replace(',', ' ') }} F</td></tr>
{% else %}<tr><td class="mut">Pas encore de données</td></tr>{% endfor %}</table></div>
</div>
""")

LIGNES = """
<div class="scroll"><table>
<tr><th>N°</th><th>Client</th><th>Livraison</th><th>Prix</th><th>Statut</th><th>Actions</th></tr>
{% for l in lignes %}<tr>
 <td>{{ l.numero }}<br><span class="mut">{{ l.cree_le }}</span></td>
 <td>{{ l.client_nom }}<br><span class="mut">{{ l.client_tel }}</span></td>
 <td>{{ l.livraison_quartier }}<br><span class="mut">{{ l.livraison_adresse }}</span></td>
 <td>{{ '{:,.0f}'.format(l.prix_course or 0).replace(',', ' ') }} F<br><span class="mut">{{ l.mode_paiement }}</span></td>
 <td><span class="tag {{ l.statut }}">{{ l.statut }}</span><br><span class="tag {{ l.statut_paiement }}">{{ l.statut_paiement }}</span></td>
 <td>
  {% if l.statut == 'en attente' %}<form class="inline" method="post" action="{{ url_for('action', id=l.id, quoi='collecte') }}"><button>Collecté</button></form>{% endif %}
  {% if l.statut in ('en attente','collecté') %}<form class="inline" method="post" action="{{ url_for('action', id=l.id, quoi='livre') }}"><button>Livré</button></form>{% endif %}
  {% if l.statut_paiement != 'payé' and l.statut != 'annulé' %}<form class="inline" method="post" action="{{ url_for('action', id=l.id, quoi='paye') }}"><button class="sec">Payé</button></form>{% endif %}
  <a class="btn sec" href="{{ url_for('modifier', id=l.id) }}">Modifier</a>
  <a class="btn sec" href="{{ url_for('facture', id=l.id) }}">Facture</a>
 </td></tr>{% endfor %}
</table></div>
"""
PAGE_ACCUEIL = PAGE_ACCUEIL.replace("{% include_rows %}", LIGNES.replace("lignes", "en_cours"))

PAGE_TOUTES = BASE.replace("{% block corps %}{% endblock %}",
                           '<div class="card"><h2>Toutes les livraisons ({{ lignes|length }})</h2>'
                           + LIGNES + "</div>")

PAGE_FORM = BASE.replace("{% block corps %}{% endblock %}", """
{% if analyse %}
<div class="card"><h2>1. Colle le message du client</h2>
<textarea id="message" rows="5" placeholder="Colle ici le message WhatsApp (texte ou transcription d'une note vocale)"></textarea>
<p><button type="button" onclick="analyser()" id="btn">Analyser le message</button>
<span id="etat" class="mut"></span></p></div>
{% endif %}
<form method="post" action="{{ cible }}" class="card">
<h2>{{ titre }}</h2>
<input type="hidden" name="message_original" id="message_original" value="{{ v.get('message_original','') }}">
<div class="grille">
{% for cle, libelle, genre, options in champs %}<div>
 <label for="{{ cle }}">{{ libelle }}</label>
 {% if genre == 'select' %}<select id="{{ cle }}" name="{{ cle }}">
  {% for o in options %}<option {{ 'selected' if v.get(cle) == o else '' }}>{{ o }}</option>{% endfor %}</select>
 {% elif genre == 'textarea' %}<textarea id="{{ cle }}" name="{{ cle }}" rows="2">{{ v.get(cle) or '' }}</textarea>
 {% elif genre == 'number' %}<input id="{{ cle }}" name="{{ cle }}" type="number" step="any" value="{{ v.get(cle) if v.get(cle) not in (None, 0, 0.0) else '' }}">
 {% else %}<input id="{{ cle }}" name="{{ cle }}" value="{{ v.get(cle) or '' }}">{% endif %}
</div>{% endfor %}</div>
<p><button type="button" class="sec" onclick="distance()">📍 Calculer la distance</button> <span id="dist" class="mut"></span></p>
<p><button>Enregistrer</button></p></form>
<script>
async function distance(){
  const g=id=>(document.getElementById(id)||{}).value||'';
  const a=[g('collecte_lieu'),g('collecte_quartier')].filter(Boolean).join(', ');
  const b=[g('livraison_adresse'),g('livraison_quartier')].filter(Boolean).join(', ');
  const el=document.getElementById('dist');
  if(!a||!b){el.textContent=' Renseigne la collecte et la livraison.';return;}
  el.textContent=' Calcul en cours…';
  try{
    const r=await fetch('{{ url_for("route_distance") }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({a:a,b:b,qa:g('collecte_quartier'),qb:g('livraison_quartier')})});
    const d=await r.json(); if(!r.ok) throw new Error(d.erreur||'Erreur');
    document.getElementById('distance_km').value=d.km;
    el.textContent=' ≈ '+d.km+' km, environ '+d.minutes+' min'+(d.approx?' · position approximative (quartier)':'')+' · © OpenStreetMap';
  }catch(e){el.textContent=' '+e.message;}
}
async function analyser(){
  const msg=document.getElementById('message').value.trim(); if(!msg)return;
  const etat=document.getElementById('etat'); etat.textContent=' Analyse en cours…';
  try{
    const r=await fetch('{{ url_for("extraire") }}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
    const d=await r.json(); if(!r.ok) throw new Error(d.erreur||'Erreur');
    for(const [k,val] of Object.entries(d)){const el=document.getElementById(k); if(el&&val!=='') el.value=val;}
    document.getElementById('message_original').value=msg;
    etat.textContent=' Vérifie les champs puis enregistre.';distance();
  }catch(e){etat.textContent=' '+e.message+' — tu peux remplir à la main.';}
}
</script>
""")


def formulaire(v, cible, titre, analyse):
    return render_template_string(PAGE_FORM, v=v, cible=cible, titre=titre,
                                  analyse=analyse, champs=CHAMPS)


@app.route("/")
def accueil():
    with db() as con:
        jour = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(prix_course),0) revenu, COALESCE(SUM(frais),0) frais "
            "FROM livraisons WHERE statut!='annulé' AND date(cree_le)=date('now','localtime')").fetchone()
        total = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(prix_course),0) revenu FROM livraisons "
            "WHERE statut!='annulé'").fetchone()
        impayes = con.execute(
            "SELECT COALESCE(SUM(prix_course),0) FROM livraisons "
            "WHERE statut='livré' AND statut_paiement!='payé'").fetchone()[0]
        en_cours = con.execute(
            "SELECT * FROM livraisons WHERE statut IN ('en attente','collecté') "
            "OR (statut='livré' AND statut_paiement!='payé') ORDER BY id DESC").fetchall()
        clients = con.execute(
            "SELECT client_nom, COUNT(*) n, COALESCE(SUM(prix_course),0) total FROM livraisons "
            "WHERE client_nom!='' AND statut!='annulé' GROUP BY client_nom ORDER BY n DESC LIMIT 5").fetchall()
        quartiers = con.execute(
            "SELECT livraison_quartier, COUNT(*) n, COALESCE(SUM(prix_course),0) total FROM livraisons "
            "WHERE livraison_quartier!='' AND statut!='annulé' GROUP BY livraison_quartier "
            "ORDER BY n DESC LIMIT 5").fetchall()
    return render_template_string(PAGE_ACCUEIL, jour=jour, total=total, impayes=impayes,
                                  en_cours=en_cours, clients=clients, quartiers=quartiers,
                                  relances=relances(), serie=serie_jours(7))


@app.route("/toutes")
def toutes():
    with db() as con:
        lignes = con.execute("SELECT * FROM livraisons ORDER BY id DESC").fetchall()
    return render_template_string(PAGE_TOUTES, lignes=lignes)


@app.route("/nouvelle", methods=["GET", "POST"])
def nouvelle():
    if request.method == "POST":
        d = lire_formulaire()
        colonnes = CLES + ["message_original", "cree_le"]
        valeurs = [d[c] for c in CLES] + [d["message_original"], maintenant()]
        with db() as con:
            cur = con.execute(
                f"INSERT INTO livraisons ({','.join(colonnes)}) VALUES ({','.join('?' * len(colonnes))})",
                valeurs)
            con.execute("UPDATE livraisons SET numero=? WHERE id=?",
                        (f"LIV-{cur.lastrowid:04d}", cur.lastrowid))
        return redirect(url_for("accueil"))
    return formulaire({"statut": "en attente", "statut_paiement": "en attente"},
                      url_for("nouvelle"), "2. Vérifie et enregistre", True)


@app.route("/modifier/<int:id>", methods=["GET", "POST"])
def modifier(id):
    if request.method == "POST":
        d = lire_formulaire()
        with db() as con:
            con.execute(f"UPDATE livraisons SET {','.join(c + '=?' for c in CLES)} WHERE id=?",
                        [d[c] for c in CLES] + [id])
        return redirect(url_for("toutes"))
    with db() as con:
        ligne = con.execute("SELECT * FROM livraisons WHERE id=?", (id,)).fetchone()
    if not ligne:
        return redirect(url_for("toutes"))
    return formulaire(dict(ligne), url_for("modifier", id=id), f"Modifier {ligne['numero']}", False)


@app.route("/action/<int:id>/<quoi>", methods=["POST"])
def action(id, quoi):
    requetes = {
        "collecte": "UPDATE livraisons SET statut='collecté', heure_collecte=? WHERE id=?",
        "livre": "UPDATE livraisons SET statut='livré', heure_livraison=? WHERE id=?",
        "paye": "UPDATE livraisons SET statut_paiement='payé', heure_paiement=? WHERE id=?",
    }
    if quoi in requetes:
        with db() as con:
            con.execute(requetes[quoi], (maintenant(), id))
    return redirect(request.referrer or url_for("accueil"))


@app.route("/extraire", methods=["POST"])
def extraire():
    message = (request.get_json(silent=True) or {}).get("message", "").strip()
    if not message:
        return jsonify(erreur="Message vide"), 400
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
        return jsonify(erreur="Aucune clé IA configurée (GEMINI_API_KEY ou ANTHROPIC_API_KEY)"), 500
    try:
        return jsonify(extraire_avec_ia(message))
    except Exception as e:  # on renvoie l'erreur à l'écran au lieu de planter
        return jsonify(erreur=f"Analyse impossible ({type(e).__name__} {getattr(e, 'code', '')})"), 500


@app.route("/export.csv")
def export():
    with db() as con:
        lignes = con.execute("SELECT * FROM livraisons ORDER BY id").fetchall()
    sortie = io.StringIO()
    if lignes:
        w = csv.writer(sortie)
        w.writerow(lignes[0].keys())
        w.writerows([tuple(l) for l in lignes])
    # BOM UTF-8 pour que Excel affiche bien les accents
    return Response("\ufeff" + sortie.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=livraisons.csv"})


# ===================== V2 : statistiques, clients, factures, relances =====================
from datetime import timedelta
from urllib.parse import quote

ENTREPRISE = {  # modifie ces lignes : elles apparaissent sur les factures
    "nom": "LIR - Livreur d'Intervention Rapide",
    "responsable": "SANON Justin",
    "tel": "07 60 66 77 / 55 28 82 36",
    "ville": "Ouagadougou, Burkina Faso",
}
EXTRA = ("CREATE TABLE IF NOT EXISTS notes_clients (cle TEXT PRIMARY KEY, note TEXT);"
         "CREATE TABLE IF NOT EXISTS geocache (cle TEXT PRIMARY KEY, lat REAL, lon REAL);")
CLE = "COALESCE(NULLIF(client_tel,''), NULLIF(client_nom,''), 'inconnu')"


def fcfa(v):
    return "{:,.0f}".format(v or 0).replace(",", " ")


def tel_wa(tel):
    n = "".join(ch for ch in (tel or "") if ch.isdigit())
    return "226" + n if len(n) == 8 else n


def lien_relance(l):
    n = tel_wa(l["client_tel"])
    if not n:
        return ""
    txt = (f"Bonjour {l['client_nom'] or ''}, petit rappel : la course {l['numero']} du "
           f"{(l['cree_le'] or '')[:10]} ({fcfa(l['prix_course'])} FCFA) n'est pas encore réglée. Merci ! - LIR")
    return f"https://wa.me/{n}?text={quote(txt)}"


app.jinja_env.filters["fcfa"] = fcfa
app.jinja_env.globals["lien_relance"] = lien_relance


def relances():
    with db() as con:
        return con.execute(
            "SELECT *, CAST(julianday('now','localtime')-julianday(COALESCE(heure_livraison,cree_le)) AS INTEGER) AS jours "
            "FROM livraisons WHERE statut='livré' AND statut_paiement!='payé' ORDER BY jours DESC").fetchall()


def serie_jours(n):
    debut = (datetime.now() - timedelta(days=n - 1)).strftime("%Y-%m-%d")
    with db() as con:
        rows = con.execute(
            "SELECT date(cree_le) j, SUM(prix_course) r, SUM(frais) f, COUNT(*) c FROM livraisons "
            "WHERE statut!='annulé' AND date(cree_le)>=? GROUP BY j", (debut,)).fetchall()
    d = {r["j"]: r for r in rows}
    jours = [datetime.now() - timedelta(days=n - 1 - i) for i in range(n)]
    out = {"labels": [j.strftime("%d/%m") for j in jours], "revenus": [], "benefices": [], "courses": []}
    for j in jours:
        r = d.get(j.strftime("%Y-%m-%d"))
        rev, fr = ((r["r"] or 0), (r["f"] or 0)) if r else (0, 0)
        out["revenus"].append(rev)
        out["benefices"].append(rev - fr)
        out["courses"].append(r["c"] if r else 0)
    return out


PAGE_STATS = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>Indicateurs clés</h2><div class="stats">
 <div class="stat"><b>{{ k.panier|fcfa }} F</b><span>Panier moyen</span></div>
 <div class="stat"><b>{{ k.net|fcfa }} F</b><span>Bénéfice net total</span></div>
 <div class="stat"><b>{{ k.par_course|fcfa }} F</b><span>Bénéfice par course</span></div>
 <div class="stat"><b>{{ k.duree }}</b><span>Durée moyenne collecte → livraison</span></div>
 <div class="stat"><b>{{ k.annul }} %</b><span>Annulées / injoignables</span></div>
 <div class="stat"><b>{{ k.km }} km</b><span>Distance totale</span></div>
</div></div>
<div class="card"><h2>Revenus et bénéfice, 30 derniers jours</h2><div class="chart"><canvas id="g1"></canvas></div></div>
<div class="grille">
<div class="card"><h2>Quartiers les plus livrés</h2><div class="chart"><canvas id="g2"></canvas></div></div>
<div class="card"><h2>Modes de paiement</h2><div class="chart"><canvas id="g3"></canvas></div></div>
<div class="card"><h2>Heures de pointe</h2><div class="chart"><canvas id="g4"></canvas></div></div>
<div class="card"><h2>Jours de la semaine</h2><div class="chart"><canvas id="g5"></canvas></div></div>
</div>
<script>
const D={{ data|tojson }};const C=['#0a7d3c','#f2a900','#2d7ff9','#d64545','#8e5bd9','#16b3a5','#e86fa4','#7a8b83'];
function mk(id,type,labels,sets,o){if(!window.Chart)return;new Chart(document.getElementById(id),{type:type,data:{labels:labels,datasets:sets},options:Object.assign({maintainAspectRatio:false,plugins:{legend:{display:sets.length>1||type==='doughnut',position:'bottom'}}},o||{})});}
mk('g1','line',D.jours.labels,[{label:'Revenus',data:D.jours.revenus,borderColor:C[0],backgroundColor:'rgba(10,125,60,.15)',fill:true,tension:.3},{label:'Bénéfice',data:D.jours.benefices,borderColor:C[1],tension:.3}]);
mk('g2','bar',D.quartiers.labels,[{label:'Courses',data:D.quartiers.v,backgroundColor:C[0],borderRadius:6}],{indexAxis:'y'});
mk('g3','doughnut',D.paiements.labels,[{data:D.paiements.v,backgroundColor:C}]);
mk('g4','bar',[...Array(24).keys()].map(h=>h+'h'),[{label:'Courses',data:D.heures,backgroundColor:C[2],borderRadius:4}]);
mk('g5','bar',['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'],[{label:'Courses',data:D.semaine,backgroundColor:C[1],borderRadius:6}]);
</script>
""")

PAGE_CLIENTS = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>Clients ({{ lignes|length }})</h2>
<form method="get"><input name="q" value="{{ q }}" placeholder="Rechercher un nom ou un numéro"></form>
<div class="scroll"><table><tr><th>Client</th><th>Courses</th><th>Total</th><th>Dernière</th><th>À encaisser</th></tr>
{% for c in lignes %}<tr><td><a href="{{ url_for('client', k=c.cle) }}">{{ c.nom or c.tel or 'Inconnu' }}</a>{% if c.n >= 5 %} <span class="tag payé">régulier</span>{% endif %}<br><span class="mut">{{ c.tel }}</span></td>
<td>{{ c.n }}</td><td>{{ c.total|fcfa }} F</td><td>{{ (c.derniere or '')[:10] }}</td>
<td>{% if c.impaye %}<b style="color:var(--rouge)">{{ c.impaye|fcfa }} F</b>{% else %}-{% endif %}</td></tr>
{% else %}<tr><td class="mut">Aucun client</td></tr>{% endfor %}</table></div></div>
""")

PAGE_CLIENT = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>{{ nom }} {% if n >= 5 %}<span class="tag payé">client régulier</span>{% endif %}</h2>
<p class="mut">{{ tel }}{% if tel %} · <a href="https://wa.me/{{ wa }}" target="_blank">Ouvrir WhatsApp</a>{% endif %}</p>
<div class="stats"><div class="stat"><b>{{ n }}</b><span>courses</span></div>
<div class="stat"><b>{{ total|fcfa }} F</b><span>total dépensé</span></div>
<div class="stat"><b>{{ panier|fcfa }} F</b><span>panier moyen</span></div>
<div class="stat"><b>{{ impaye|fcfa }} F</b><span>à encaisser</span></div></div>
{% if impaye and relance %}<p><a class="btn" target="_blank" href="{{ relance }}">Relancer sur WhatsApp</a></p>{% endif %}</div>
<div class="card"><h2>Profil et habitudes</h2><div class="stats">
<div class="stat"><b>{{ profil.type or '-' }}</b><span>Type de client</span></div>
<div class="stat"><b>{{ profil.source or '-' }}</b><span>Comment il nous a connus</span></div>
<div class="stat"><b>{{ profil.quartier or '-' }}</b><span>Quartier</span></div>
<div class="stat"><b>{{ profil.freq or '-' }}</b><span>Délai moyen entre commandes</span></div>
<div class="stat"><b>{{ profil.premiere or '-' }}</b><span>Première commande</span></div>
<div class="stat"><b>{{ profil.derniere or '-' }}</b><span>Dernière commande</span></div></div>
<div class="grille" style="margin-top:14px">
<div><h2>Produits commandés</h2>{% for p, k in profil.produits %}<div class="ligne"><span>{{ p }}</span><span class="tag">{{ k }}x</span></div>{% else %}<p class="mut">Pas encore renseigné</p>{% endfor %}</div>
<div><h2>Boutiques / fournisseurs</h2>{% for p, k in profil.boutiques %}<div class="ligne"><span>{{ p }}</span><span class="tag">{{ k }}x</span></div>{% else %}<p class="mut">Pas encore renseigné</p>{% endfor %}</div>
<div><h2>Quartiers livrés</h2>{% for p, k in profil.quartiers %}<div class="ligne"><span>{{ p }}</span><span class="tag">{{ k }}x</span></div>{% else %}<p class="mut">Pas encore renseigné</p>{% endfor %}</div>
</div></div>
<form method="post" class="card"><h2>Notes sur ce client</h2><input type="hidden" name="k" value="{{ cle }}">
<textarea name="note" rows="3" placeholder="Ex : préfère être livré après 18h, paie par Orange Money…">{{ note }}</textarea>
<p><button>Enregistrer la note</button></p></form>
<div class="card"><h2>Historique</h2>""" + LIGNES + "</div>")

PAGE_FACTURE = """<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Facture {{ l.numero }}</title>
<style>body{font-family:system-ui,Arial,sans-serif;max-width:720px;margin:24px auto;padding:0 16px;color:#111}
h1{margin:0;color:#0a7d3c}.top{display:flex;justify-content:space-between;border-bottom:3px solid #0a7d3c;padding-bottom:12px}
table{width:100%;border-collapse:collapse;margin:20px 0}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}
.tot{font-size:1.3rem;text-align:right}.stamp{display:inline-block;border:3px solid;padding:4px 14px;border-radius:8px;font-weight:700;transform:rotate(-6deg);margin-left:12px}
.ok{color:#0a7d3c}.no{color:#c0392b}button{background:#0a7d3c;color:#fff;border:0;padding:10px 16px;border-radius:8px;font-size:1rem;cursor:pointer}
@media print{.noprint{display:none}}</style></head><body>
<p class="noprint"><button onclick="window.print()">Imprimer / enregistrer en PDF</button> <a href="{{ url_for('toutes') }}">Retour</a></p>
<div class="top"><div><h1>FACTURE</h1><b>{{ l.numero|replace('LIV','FAC') }}</b><br>Date : {{ (l.cree_le or '')[:10] }}</div>
<div style="text-align:right"><b>{{ e.nom }}</b><br>{{ e.responsable }}<br>{{ e.tel }}<br>{{ e.ville }}</div></div>
<p><b>Client :</b> {{ l.client_nom }} {{ l.client_tel }}</p>
<table><tr><th>Description</th><th style="text-align:right">Montant</th></tr>
<tr><td>Course de livraison<br><small>{{ l.collecte_lieu or l.collecte_quartier }} → {{ l.livraison_adresse or l.livraison_quartier }}</small></td><td style="text-align:right">{{ l.prix_course|fcfa }} F</td></tr>
{% if l.valeur_produit %}<tr><td>Produit avancé : {{ l.colis }}</td><td style="text-align:right">{{ l.valeur_produit|fcfa }} F</td></tr>{% endif %}</table>
<p class="tot"><b>Total : {{ total|fcfa }} FCFA</b></p>
<p>Mode de paiement : {{ l.mode_paiement }}{% if l.statut_paiement == 'payé' %}<span class="stamp ok">PAYÉ</span>{% else %}<span class="stamp no">À PAYER</span>{% endif %}</p>
<p><small>Merci de votre confiance.</small></p></body></html>"""


@app.route("/stats")
def stats():
    with db() as con:
        k = con.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(prix_course),0) rev, COALESCE(SUM(frais),0) fr, "
            "COALESCE(AVG(prix_course),0) panier, COALESCE(SUM(distance_km),0) km "
            "FROM livraisons WHERE statut!='annulé'").fetchone()
        tot = con.execute("SELECT COUNT(*) FROM livraisons").fetchone()[0]
        perdu = con.execute("SELECT COUNT(*) FROM livraisons WHERE statut IN ('annulé','injoignable')").fetchone()[0]
        duree = con.execute(
            "SELECT AVG((julianday(heure_livraison)-julianday(heure_collecte))*1440) FROM livraisons "
            "WHERE heure_collecte IS NOT NULL AND heure_livraison IS NOT NULL").fetchone()[0]
        quartiers = con.execute(
            "SELECT livraison_quartier l, COUNT(*) n FROM livraisons WHERE livraison_quartier!='' "
            "AND statut!='annulé' GROUP BY l ORDER BY n DESC LIMIT 8").fetchall()
        paiements = con.execute(
            "SELECT mode_paiement l, COUNT(*) n FROM livraisons WHERE mode_paiement!='' "
            "AND statut!='annulé' GROUP BY l").fetchall()
        heures = {r["h"]: r["n"] for r in con.execute(
            "SELECT strftime('%H', cree_le) h, COUNT(*) n FROM livraisons WHERE statut!='annulé' GROUP BY h")}
        semaine = {r["d"]: r["n"] for r in con.execute(
            "SELECT strftime('%w', cree_le) d, COUNT(*) n FROM livraisons WHERE statut!='annulé' GROUP BY d")}
    net = k["rev"] - k["fr"]
    kpi = {
        "panier": k["panier"], "net": net, "par_course": net / k["n"] if k["n"] else 0,
        "duree": f"{duree:.0f} min" if duree else "-",
        "annul": round(100 * perdu / tot) if tot else 0, "km": round(k["km"]),
    }
    data = {
        "jours": serie_jours(30),
        "quartiers": {"labels": [r["l"] for r in quartiers], "v": [r["n"] for r in quartiers]},
        "paiements": {"labels": [r["l"] for r in paiements], "v": [r["n"] for r in paiements]},
        "heures": [heures.get(f"{i:02d}", 0) for i in range(24)],
        "semaine": [semaine.get(str(i), 0) for i in (1, 2, 3, 4, 5, 6, 0)],
    }
    return render_template_string(PAGE_STATS, k=kpi, data=data)


@app.route("/clients")
def clients():
    q = request.args.get("q", "").strip().lower()
    with db() as con:
        lignes = con.execute(
            f"SELECT {CLE} cle, MAX(client_nom) nom, MAX(client_tel) tel, COUNT(*) n, "
            "COALESCE(SUM(CASE WHEN statut!='annulé' THEN prix_course END),0) total, MAX(cree_le) derniere, "
            "COALESCE(SUM(CASE WHEN statut='livré' AND statut_paiement!='payé' THEN prix_course END),0) impaye "
            "FROM livraisons GROUP BY cle ORDER BY total DESC").fetchall()
    if q:
        lignes = [l for l in lignes if q in (l["nom"] or "").lower() or (chiffres(q) and chiffres(q) in chiffres(l["tel"]))]
    return render_template_string(PAGE_CLIENTS, lignes=lignes, q=q)


@app.route("/client", methods=["GET", "POST"])
def client():
    cle = request.values.get("k", "")
    with db() as con:
        if request.method == "POST":
            con.execute("INSERT INTO notes_clients(cle,note) VALUES(?,?) "
                        "ON CONFLICT(cle) DO UPDATE SET note=excluded.note", (cle, request.form.get("note", "")))
        lignes = con.execute(f"SELECT * FROM livraisons WHERE {CLE}=? ORDER BY id DESC", (cle,)).fetchall()
        note = con.execute("SELECT note FROM notes_clients WHERE cle=?", (cle,)).fetchone()
    if not lignes:
        return redirect(url_for("clients"))
    ok = [l for l in lignes if l["statut"] != "annulé"]
    total = sum(l["prix_course"] or 0 for l in ok)
    dus = [l for l in lignes if l["statut"] == "livré" and l["statut_paiement"] != "payé"]
    nom = next((l["client_nom"] for l in lignes if l["client_nom"]), "") or "Client"
    tel = next((l["client_tel"] for l in lignes if l["client_tel"]), "")
    return render_template_string(
        PAGE_CLIENT, lignes=lignes, cle=cle, nom=nom, tel=tel, wa=tel_wa(tel), n=len(ok), total=total,
        panier=total / len(ok) if ok else 0, impaye=sum(l["prix_course"] or 0 for l in dus),
        relance=lien_relance(dus[0]) if dus else "", note=note["note"] if note else "",
        profil=profil_client(lignes))


@app.route("/facture/<int:id>")
def facture(id):
    with db() as con:
        l = con.execute("SELECT * FROM livraisons WHERE id=?", (id,)).fetchone()
    if not l:
        return redirect(url_for("toutes"))
    total = (l["prix_course"] or 0) + (l["valeur_produit"] or 0)
    return render_template_string(PAGE_FACTURE, l=l, e=ENTREPRISE, total=total)


# ===================== V3 : recherche globale, produits, marché =====================
def chiffres(t):
    n = "".join(ch for ch in (t or "") if ch.isdigit())
    return n[3:] if n.startswith("226") and len(n) > 8 else n


def migrer(con):
    """Ajoute les nouvelles colonnes à une ancienne base sans perdre les données."""
    existantes = {r[1] for r in con.execute("PRAGMA table_info(livraisons)")}
    for cle, _, _, _ in CHAMPS:
        if cle not in existantes:
            con.execute(f"ALTER TABLE livraisons ADD COLUMN {cle} {'REAL' if cle in NOMBRES else 'TEXT'}")
    for r in con.execute("SELECT id, client_tel, destinataire_tel FROM livraisons").fetchall():
        a, b = chiffres(r[1]), chiffres(r[2])
        if (a, b) != ((r[1] or ""), (r[2] or "")):
            con.execute("UPDATE livraisons SET client_tel=?, destinataire_tel=? WHERE id=?", (a, b, r[0]))


def lien_reprise(c):
    n = tel_wa(c["tel"])
    if not n:
        return ""
    txt = (f"Bonjour {c['nom'] or ''}, ça fait un moment ! LIR reste disponible pour toutes vos "
           "livraisons rapides. N'hésitez pas à nous écrire 🏍️")
    return f"https://wa.me/{n}?text={quote(txt)}"


app.jinja_env.globals["lien_reprise"] = lien_reprise


def profil_client(lignes):
    ok = [l for l in lignes if l["statut"] != "annulé"]

    def top(cle):
        c = {}
        for l in ok:
            v = (l[cle] or "").strip()
            if v:
                c[v] = c.get(v, 0) + 1
        return sorted(c.items(), key=lambda x: -x[1])[:5]

    def dernier(cle):
        return next((l[cle] for l in lignes if l[cle]), "")

    dates = sorted((l["cree_le"] or "")[:10] for l in ok if l["cree_le"])
    freq = ""
    if len(dates) > 1:
        d0, d1 = (datetime.strptime(d, "%Y-%m-%d") for d in (dates[0], dates[-1]))
        freq = f"{(d1 - d0).days / (len(dates) - 1):.0f} jours"
    return {"type": dernier("type_client"), "source": dernier("source_client"),
            "quartier": dernier("client_quartier") or dernier("livraison_quartier"),
            "premiere": dates[0] if dates else "", "derniere": dates[-1] if dates else "", "freq": freq,
            "produits": top("produit"), "boutiques": top("collecte_lieu"), "quartiers": top("livraison_quartier")}


PAGE_RECHERCHE = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>Clients trouvés pour « {{ q }} » ({{ cl|length }})</h2>
<div class="scroll"><table><tr><th>Client</th><th>Courses</th><th>Total</th><th>À encaisser</th></tr>
{% for c in cl %}<tr><td><a href="{{ url_for('client', k=c.cle) }}">{{ c.nom or c.tel or 'Inconnu' }}</a><br><span class="mut">{{ c.tel }}</span></td>
<td>{{ c.n }}</td><td>{{ c.total|fcfa }} F</td><td>{{ c.impaye|fcfa }} F</td></tr>
{% else %}<tr><td class="mut">Aucun client trouvé</td></tr>{% endfor %}</table></div></div>
<div class="card"><h2>Livraisons trouvées ({{ lignes|length }})</h2>""" + LIGNES + "</div>")

PAGE_MARCHE = BASE.replace("{% block corps %}{% endblock %}", """
<div class="card"><h2>Clients</h2><div class="stats">
 <div class="stat"><b>{{ kc.total }}</b><span>clients</span></div>
 <div class="stat"><b>{{ kc.nouveaux }}</b><span>nouveaux (30 jours)</span></div>
 <div class="stat"><b>{{ kc.fideles }}</b><span>reviennent (2 courses ou +)</span></div>
 <div class="stat"><b>{{ kc.reguliers }}</b><span>réguliers (5 ou +)</span></div>
 <div class="stat"><b>{{ kc.taux }} %</b><span>taux de fidélité</span></div>
 <div class="stat"><b>{{ kc.inactifs }}</b><span>inactifs (+30 jours)</span></div></div></div>
{% if not produits %}<div class="card"><p class="mut">Renseigne la catégorie et le produit à chaque livraison : cette page se remplit au fur et à mesure.</p></div>{% endif %}
<div class="grille">
<div class="card"><h2>Produits les plus demandés</h2><div class="chart"><canvas id="m1"></canvas></div></div>
<div class="card"><h2>Catégories de produits</h2><div class="chart"><canvas id="m2"></canvas></div></div>
<div class="card"><h2>Types de clients</h2><div class="chart"><canvas id="m3"></canvas></div></div>
<div class="card"><h2>Boutiques / fournisseurs sollicités</h2><div class="chart"><canvas id="m4"></canvas></div></div>
</div>
<div class="card"><h2>Détail par produit</h2><div class="scroll"><table>
<tr><th>Produit</th><th>Catégorie</th><th>Commandes</th><th>Quantité</th><th>Clients</th><th>Valeur moy.</th></tr>
{% for p in produits %}<tr><td>{{ p.produit }}</td><td>{{ p.categorie or '-' }}</td><td>{{ p.n }}</td><td>{{ p.qte|round|int }}</td><td>{{ p.clients }}</td><td>{{ p.valeur|fcfa }} F</td></tr>
{% else %}<tr><td class="mut">Pas encore de données</td></tr>{% endfor %}</table></div></div>
<div class="card"><h2>Quartiers : où est la demande ?</h2><div class="scroll"><table>
<tr><th>Quartier</th><th>Courses</th><th>Clients</th><th>Revenu</th><th>Panier moyen</th></tr>
{% for q in quartiers %}<tr><td>{{ q.l }}</td><td>{{ q.n }}</td><td>{{ q.clients }}</td><td>{{ q.r|fcfa }} F</td><td>{{ q.p|fcfa }} F</td></tr>
{% else %}<tr><td class="mut">Pas encore de données</td></tr>{% endfor %}</table></div></div>
<div class="card"><h2>Clients à réactiver ({{ kc.inactifs }})</h2>
{% for c in inactifs %}<div class="ligne"><div><b>{{ c.nom or c.tel }}</b><br><span class="mut">{{ c.n }} courses · {{ c.total|fcfa }} F · dernière il y a {{ c.jours }} j</span></div>
{% if lien_reprise(c) %}<a class="btn" target="_blank" href="{{ lien_reprise(c) }}">Reprendre contact</a>{% endif %}</div>
{% else %}<p class="mut">Aucun client inactif pour le moment.</p>{% endfor %}</div>
<script>
const D={{ data|tojson }};const C=['#0a7d3c','#f2a900','#2d7ff9','#d64545','#8e5bd9','#16b3a5','#e86fa4','#7a8b83'];
function mk(id,type,d,o){if(!window.Chart||!d.l.length)return;new Chart(document.getElementById(id),{type:type,data:{labels:d.l,datasets:[{data:d.v,backgroundColor:type==='doughnut'?C:C[0],borderRadius:6}]},options:Object.assign({maintainAspectRatio:false,plugins:{legend:{display:type==='doughnut',position:'bottom'}}},o||{})});}
mk('m1','bar',D.produits,{indexAxis:'y'});mk('m2','doughnut',D.categories);mk('m3','doughnut',D.types);mk('m4','bar',D.boutiques,{indexAxis:'y'});
</script>
""")


@app.route("/recherche")
def recherche():
    q = request.args.get("q", "").strip()
    if not q:
        return redirect(url_for("clients"))
    qd, like = chiffres(q), f"%{q.lower()}%"
    propre = lambda col: f"REPLACE(REPLACE({col},' ',''),'-','')"
    cond_c, par_c = ["LOWER(COALESCE(client_nom,'')) LIKE ?"], [like]
    champs = ["client_nom", "colis", "produit", "categorie", "collecte_lieu", "livraison_quartier",
              "livraison_adresse", "destinataire_nom", "numero", "remarques"]
    cond_l, par_l = [f"LOWER(COALESCE({c},'')) LIKE ?" for c in champs], [like] * len(champs)
    if len(qd) >= 3:
        cond_c.append(f"{propre('client_tel')} LIKE ?")
        par_c.append(f"%{qd}%")
        cond_l += [f"{propre('client_tel')} LIKE ?", f"{propre('destinataire_tel')} LIKE ?"]
        par_l += [f"%{qd}%"] * 2
    with db() as con:
        cl = con.execute(
            f"SELECT {CLE} cle, MAX(client_nom) nom, MAX(client_tel) tel, COUNT(*) n, "
            "COALESCE(SUM(CASE WHEN statut!='annulé' THEN prix_course END),0) total, "
            "COALESCE(SUM(CASE WHEN statut='livré' AND statut_paiement!='payé' THEN prix_course END),0) impaye "
            f"FROM livraisons WHERE {CLE} IN (SELECT {CLE} FROM livraisons WHERE {' OR '.join(cond_c)}) "
            "GROUP BY cle ORDER BY total DESC", par_c).fetchall()
        lignes = con.execute(f"SELECT * FROM livraisons WHERE {' OR '.join(cond_l)} ORDER BY id DESC LIMIT 100",
                             par_l).fetchall()
    return render_template_string(PAGE_RECHERCHE, q=q, cl=cl, lignes=lignes)


@app.route("/marche")
def marche():
    ok = "statut!='annulé'"
    with db() as con:
        rows = lambda sql: con.execute(sql).fetchall()
        cl = rows(f"SELECT {CLE} cle, MAX(client_nom) nom, MAX(client_tel) tel, COUNT(*) n, MIN(date(cree_le)) premiere, "
                  f"MAX(date(cree_le)) derniere, COALESCE(SUM(prix_course),0) total FROM livraisons WHERE {ok} GROUP BY cle")
        produits = rows(
            "SELECT MIN(produit) produit, MAX(categorie) categorie, COUNT(*) n, "
            f"SUM(CASE WHEN quantite>0 THEN quantite ELSE 1 END) qte, COUNT(DISTINCT {CLE}) clients, "
            f"COALESCE(AVG(NULLIF(valeur_produit,0)),0) valeur FROM livraisons WHERE {ok} AND produit!='' "
            "GROUP BY LOWER(produit) ORDER BY n DESC LIMIT 15")
        categories = rows(f"SELECT categorie l, COUNT(*) n FROM livraisons WHERE {ok} AND categorie!='' GROUP BY l ORDER BY n DESC")
        types = rows(f"SELECT type_client l, COUNT(*) n FROM livraisons WHERE {ok} AND type_client!='' GROUP BY l ORDER BY n DESC")
        boutiques = rows(f"SELECT MIN(collecte_lieu) l, COUNT(*) n FROM livraisons WHERE {ok} AND collecte_lieu!='' "
                         "GROUP BY LOWER(collecte_lieu) ORDER BY n DESC LIMIT 8")
        quartiers = rows(
            f"SELECT MIN(livraison_quartier) l, COUNT(*) n, COUNT(DISTINCT {CLE}) clients, COALESCE(SUM(prix_course),0) r, "
            f"COALESCE(AVG(prix_course),0) p FROM livraisons WHERE {ok} AND livraison_quartier!='' "
            "GROUP BY LOWER(livraison_quartier) ORDER BY n DESC LIMIT 10")
    auj = datetime.now().date()
    jours = lambda d: (auj - datetime.strptime(d, "%Y-%m-%d").date()).days
    cl = [c for c in cl if c["derniere"]]
    kc = {"total": len(cl), "nouveaux": sum(1 for c in cl if jours(c["premiere"]) <= 30),
          "fideles": sum(1 for c in cl if c["n"] >= 2), "reguliers": sum(1 for c in cl if c["n"] >= 5)}
    kc["taux"] = round(100 * kc["fideles"] / kc["total"]) if kc["total"] else 0
    inactifs = sorted((dict(c, jours=jours(c["derniere"])) for c in cl if jours(c["derniere"]) > 30),
                      key=lambda c: -c["total"])
    kc["inactifs"] = len(inactifs)
    paire = lambda r: {"l": [x["l"] for x in r], "v": [x["n"] for x in r]}
    data = {"produits": {"l": [p["produit"] for p in produits[:8]], "v": [p["n"] for p in produits[:8]]},
            "categories": paire(categories), "types": paire(types), "boutiques": paire(boutiques)}
    return render_template_string(PAGE_MARCHE, kc=kc, produits=produits, quartiers=quartiers,
                                  inactifs=inactifs[:10], data=data)


# ===================== V4 : IA gratuite (Gemini) + distance automatique =====================
import time
import urllib.parse
import urllib.request
from math import asin, cos, radians, sin, sqrt

UA = "LIR-Livraisons/1.0 (contact: " + os.environ.get("OSM_CONTACT", "usage-personnel") + ")"
VIEWBOX = "-1.75,12.52,-1.30,12.22"  # zone de Ouagadougou
_dernier_geocodage = [0.0]


def _http_json(url, corps=None, entetes=None, delai=20):
    req = urllib.request.Request(
        url, data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={"User-Agent": UA, "Content-Type": "application/json", **(entetes or {})})
    with urllib.request.urlopen(req, timeout=delai) as r:
        return json.loads(r.read().decode("utf-8"))


def _lire_json(texte):
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("Réponse de l'IA illisible")
    brut = json.loads(texte[debut:fin + 1])
    return {k: ("" if brut.get(k) is None else brut.get(k)) for k in CLES}


def extraire_avec_gemini(message):
    modele = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    rep = _http_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent",
        {"systemInstruction": {"parts": [{"text": PROMPT_SYSTEME}]},
         "contents": [{"role": "user", "parts": [{"text": message}]}],
         "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
        {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    return _lire_json(rep["candidates"][0]["content"]["parts"][0]["text"])


def extraire_avec_ia(message):
    """Essaie Gemini (gratuit) puis Claude, ou l'inverse si IA_FOURNISSEUR=claude."""
    moteurs = []
    if os.environ.get("GEMINI_API_KEY"):
        moteurs.append(extraire_avec_gemini)
    if os.environ.get("ANTHROPIC_API_KEY"):
        moteurs.append(extraire_avec_claude)
    if os.environ.get("IA_FOURNISSEUR", "").lower() == "claude":
        moteurs.reverse()
    erreur = RuntimeError("Aucune clé IA configurée")
    for moteur in moteurs:
        try:
            return moteur(message)
        except Exception as e:  # on essaie le moteur suivant
            erreur = e
    raise erreur


def geocoder(texte):
    texte = " ".join((texte or "").split())
    if not texte:
        return None
    with db() as con:
        r = con.execute("SELECT lat, lon FROM geocache WHERE cle=?", (texte.lower(),)).fetchone()
    if r:
        return (r["lat"], r["lon"]) if r["lat"] is not None else None
    attente = 1.1 - (time.time() - _dernier_geocodage[0])  # Nominatim : 1 requête/seconde maximum
    if attente > 0:
        time.sleep(attente)
    res = _http_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": texte + ", Ouagadougou", "format": "json", "limit": 1, "countrycodes": "bf",
         "viewbox": VIEWBOX, "bounded": 1}))
    _dernier_geocodage[0] = time.time()
    pos = (float(res[0]["lat"]), float(res[0]["lon"])) if res else None
    with db() as con:
        con.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)",
                    (texte.lower(), pos[0] if pos else None, pos[1] if pos else None))
    return pos


def vol_oiseau_km(p, q):
    la1, lo1, la2, lo2 = map(radians, (p[0], p[1], q[0], q[1]))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


@app.route("/distance", methods=["POST"])
def route_distance():
    d = request.get_json(silent=True) or {}
    try:
        approx, pts = False, []
        for plein, quartier in ((d.get("a", ""), d.get("qa", "")), (d.get("b", ""), d.get("qb", ""))):
            p = geocoder(plein)
            if not p and quartier and quartier != plein:
                p, approx = geocoder(quartier), True
            if not p:
                return jsonify(erreur=f"Lieu introuvable : {plein}"), 404
            pts.append(p)
        if os.environ.get("ROUTAGE", "").lower() == "osrm":  # trajet routier réel (serveur OSRM)
            base = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
            r = _http_json(f"{base}/route/v1/driving/{pts[0][1]},{pts[0][0]};{pts[1][1]},{pts[1][0]}?overview=false")
            km, minutes = r["routes"][0]["distance"] / 1000, r["routes"][0]["duration"] / 60
        else:  # estimation : distance à vol d'oiseau x 1,3, vitesse moyenne 25 km/h en ville
            km = vol_oiseau_km(*pts) * 1.3
            minutes = km / 25 * 60
        return jsonify(km=round(km, 1), minutes=round(minutes), approx=approx)
    except Exception as e:
        return jsonify(erreur=f"Calcul impossible ({type(e).__name__})"), 500


if __name__ == "__main__":
    init_db()
    # host 0.0.0.0 : accessible aussi depuis ton téléphone sur le même Wi-Fi
    app.run(host="0.0.0.0", port=5000, debug=False)
