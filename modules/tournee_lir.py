"""Module « Tournée » de LIR : assignation intelligente, itinéraire du livreur, suivi GPS économe.

1. ASSIGNATION. Une nouvelle commande n'est plus donnée au livreur « le plus proche », mais à celui qui peut
   la livrer le plus vite SANS retarder ses autres courses. Pour chaque livreur on calcule sa meilleure tournée
   avec puis sans la nouvelle commande (ordre des arrêts optimisé, récupération avant livraison) :
       score = minutes avant la livraison de la nouvelle commande
             + 1,5 x minutes de retard imposées à ses autres livraisons
   Un livreur qui part vers l'ouest ne reçoit donc pas une commande vers l'est : le retard imposé est trop grand.
2. ITINÉRAIRE. Page « Itinéraire » dans l'espace livreur : l'ordre conseillé de ses arrêts + lien Google Maps.
3. BATTERIE. Le partage de position n'utilise plus l'écran toujours allumé ni le GPS continu : une position
   toutes les ~100 s tant que la page est ouverte. Entre deux positions, l'appli estime où se trouve le livreur
   grâce à ses dernières collectes et livraisons.

Ce module est indépendant d'app.py : wsgi.py l'importe après init_db().
"""
import re
import time
import urllib.parse
from datetime import datetime

from flask import redirect, render_template_string, request, url_for

import app as A

app = A.app
log = getattr(A, "log", None)

VITESSE_KMH = 25.0       # vitesse moyenne d'une moto en ville, arrêts compris
FACTEUR_ROUTE = 1.3      # la route est plus longue que la ligne droite
MIN_ARRET = 4.0          # minutes passées à chaque arrêt (remise, paiement…)
POIDS_RETARD = 1.5       # un retard imposé à une autre livraison compte 1,5 fois
GPS_FRAIS_MIN = 20       # position GPS considérée « en direct » pendant 20 minutes
EVENEMENT_MAX_MIN = 90   # une collecte/livraison récente sert de position pendant 90 minutes
ANCIENNE_MAX_H = 3       # dernière position GPS connue utilisable pendant 3 heures
MAX_ARRETS_EXACT = 8     # au-delà, tournée approchée (le plus proche d'abord)


# ----------------------------------------------------------------------------- positions
def _texte(*parties):
    return ", ".join(p for p in parties if p)


def _cle(t):
    return " ".join((t or "").split()).lower()


def _pos_texte(con, textes, budget):
    """Coordonnées d'un lieu : cache d'abord, puis (dans la limite du budget) géocodage en ligne."""
    textes = [t for t in textes if _cle(t)]
    for t in textes:
        r = con.execute("SELECT lat, lon FROM geocache WHERE cle=?", (_cle(t),)).fetchone()
        if r and r["lat"] is not None:
            return (r["lat"], r["lon"])
    for t in textes:
        r = con.execute("SELECT 1 FROM geocache WHERE cle=?", (_cle(t),)).fetchone()
        if r or budget[0] <= 0:
            continue  # déjà essayé sans succès, ou plus de budget : on évite d'attendre le réseau
        budget[0] -= 1
        try:
            pos = A.geocoder(t)
        except Exception:
            pos = None
        if pos:
            return pos
    return None


def _pos_collecte(con, l, budget):
    return _pos_texte(con, [_texte(l["collecte_lieu"], l["collecte_quartier"]), l["collecte_lieu"], l["collecte_quartier"]], budget)


def _pos_livraison(con, l, budget):
    return _pos_texte(con, [_texte(l["livraison_adresse"], l["livraison_quartier"]), l["livraison_adresse"], l["livraison_quartier"]], budget)


def _ts(texte):
    try:
        return time.mktime(datetime.strptime((texte or "")[:16], "%Y-%m-%d %H:%M").timetuple())
    except ValueError:
        return 0.0


def position_livreur(con, lv, budget):
    """(position, source, âge en minutes) : GPS récent > dernière collecte/livraison > ancien GPS > quartier de base."""
    maintenant = time.time()
    gps = con.execute("SELECT lat, lon, maj_ts FROM positions_livreurs WHERE livreur_id=?", (lv["id"],)).fetchone()
    if gps and maintenant - gps["maj_ts"] <= GPS_FRAIS_MIN * 60:
        return (gps["lat"], gps["lon"]), "GPS", (maintenant - gps["maj_ts"]) / 60
    evenement = None  # (horodatage, position)
    for l in con.execute("SELECT * FROM livraisons WHERE livreur=? AND (COALESCE(heure_collecte,'')!='' OR COALESCE(heure_livraison,'')!='') "
                         "ORDER BY id DESC LIMIT 6", (lv["nom"],)):
        for ts, chercher in ((_ts(l["heure_livraison"]), _pos_livraison), (_ts(l["heure_collecte"]), _pos_collecte)):
            if ts and maintenant - ts <= EVENEMENT_MAX_MIN * 60 and (evenement is None or ts > evenement[0]):
                pos = chercher(con, l, budget)
                if pos:
                    evenement = (ts, pos)
    ancien = gps if gps and maintenant - gps["maj_ts"] <= ANCIENNE_MAX_H * 3600 else None
    if evenement and (not ancien or evenement[0] > ancien["maj_ts"]):
        return evenement[1], "dernière course", (maintenant - evenement[0]) / 60
    if ancien:
        return (ancien["lat"], ancien["lon"]), "dernière position", (maintenant - ancien["maj_ts"]) / 60
    if lv["base"]:
        try:
            pos = _pos_texte(con, [lv["base"]], budget)
        except Exception:
            pos = None
        if pos:
            return pos, "quartier de base", None
    return None, "inconnue", None


# ----------------------------------------------------------------------------- tournée optimale
def _km(a, b):
    return A.vol_oiseau_km(a, b) * FACTEUR_ROUTE


def _minutes(a, b):
    return _km(a, b) / VITESSE_KMH * 60 + MIN_ARRET


def meilleure_tournee(depart, arrets):
    """arrets : liste de dicts {course, type 'P'|'D', pos, poids}. 'P' = récupérer, 'D' = livrer.
    Une livraison dont la récupération est dans la liste vient toujours après. Minimise la somme pondérée des
    heures d'arrivée des arrêts qui ont un poids (les livraisons). Renvoie [(arret, minutes depuis maintenant, km)]."""
    a_recuperer = {a["course"] for a in arrets if a["type"] == "P"}
    n = len(arrets)
    if n == 0:
        return []
    if n > MAX_ARRETS_EXACT:  # trop d'arrêts pour tout essayer : on va toujours au plus proche arrêt autorisé
        reste, ordre, pos, t, pris = list(arrets), [], depart, 0.0, set()
        while reste:
            permis = [a for a in reste if not (a["type"] == "D" and a["course"] in a_recuperer and a["course"] not in pris)]
            a = min(permis, key=lambda x: _km(pos, x["pos"]))
            t += _minutes(pos, a["pos"])
            ordre.append((a, t, _km(pos, a["pos"])))
            pos = a["pos"]
            reste.remove(a)
            if a["type"] == "P":
                pris.add(a["course"])
        return ordre
    meilleur = [float("inf"), None]

    def explorer(pos, reste, t, cout, ordre, pris):
        if cout >= meilleur[0]:
            return
        if not reste:
            meilleur[0], meilleur[1] = cout, ordre
            return
        for i, a in enumerate(reste):
            if a["type"] == "D" and a["course"] in a_recuperer and a["course"] not in pris:
                continue
            d = _km(pos, a["pos"])
            t2 = t + d / VITESSE_KMH * 60 + MIN_ARRET
            explorer(a["pos"], reste[:i] + reste[i + 1:], t2, cout + a["poids"] * t2,
                     ordre + [(a, t2, d)], pris | {a["course"]} if a["type"] == "P" else pris)

    explorer(depart, list(arrets), 0.0, 0.0, [], frozenset())
    return meilleur[1] or []


def courses_ouvertes(con, nom_livreur, exclu_id, budget):
    """Courses en cours d'un livreur sous forme d'arrêts. 'en attente' = à récupérer puis livrer ; 'collecté' = à livrer."""
    arrets, sans_position = [], []
    for l in con.execute("SELECT * FROM livraisons WHERE livreur=? AND statut IN ('en attente','collecté') AND id!=? ORDER BY id",
                         (nom_livreur, exclu_id or 0)):
        pos_d = _pos_livraison(con, l, budget)
        pos_p = _pos_collecte(con, l, budget) if l["statut"] == "en attente" else None
        info = {"course": l["id"], "numero": l["numero"]}
        if l["statut"] == "en attente":
            if pos_p:
                arrets.append(dict(info, type="P", pos=pos_p, poids=0.0, lieu=_texte(l["collecte_lieu"], l["collecte_quartier"])))
            else:
                sans_position.append((l["numero"], "Récupérer", _texte(l["collecte_lieu"], l["collecte_quartier"])))
        if pos_d:
            arrets.append(dict(info, type="D", pos=pos_d, poids=1.0, lieu=_texte(l["livraison_adresse"], l["livraison_quartier"])))
        else:
            sans_position.append((l["numero"], "Livrer", _texte(l["livraison_adresse"], l["livraison_quartier"])))
    # une livraison sans lieu de récupération connu est traitée comme déjà récupérée
    return arrets, sans_position


# ----------------------------------------------------------------------------- 1. assignation intelligente
def _commande_a_attribuer(con, collecte):
    cible = _cle(collecte)
    for r in con.execute("SELECT * FROM livraisons WHERE statut='en attente' ORDER BY id DESC LIMIT 15"):
        if _cle(_texte(r["collecte_lieu"], r["collecte_quartier"])) == cible:
            return r
    return None


def classer_livreurs_tournee(collecte, quartier):
    """Remplace app.classer_livreurs : même résultat (liste triée, approx) mais classée par « qui livre le plus vite
    sans compromettre ses autres courses »."""
    pos, approx = A.geocoder(collecte), False
    if not pos and quartier and quartier != collecte:
        pos, approx = A.geocoder(quartier), True
    if not pos:
        raise LookupError(f"Lieu de collecte introuvable : {collecte}")
    budget = [8]
    with A.db() as con:
        commande = _commande_a_attribuer(con, collecte)
        pos_dest = _pos_livraison(con, commande, budget) if commande else None
        actifs = con.execute("SELECT * FROM livreurs WHERE actif=1 ORDER BY id").fetchall()
        liste = []
        for lv in actifs:
            pos_lv, source, age = position_livreur(con, lv, budget)
            if not pos_lv:
                continue
            existants, _ = courses_ouvertes(con, lv["nom"], commande["id"] if commande else None, budget)
            avant = {(a["course"], a["type"]): t for a, t, _d in meilleure_tournee(pos_lv, existants) if a["type"] == "D"}
            nouveaux = [{"course": -1, "type": "P", "pos": pos, "poids": 0.0 if pos_dest else 1.0}]
            if pos_dest:
                nouveaux.append({"course": -1, "type": "D", "pos": pos_dest, "poids": 1.0})
            apres = meilleure_tournee(pos_lv, existants + nouveaux)
            heures = {(a["course"], a["type"]): t for a, t, _d in apres}
            minutes_nouvelle = heures.get((-1, "D" if pos_dest else "P"), 0.0)
            retard = sum(max(0.0, heures.get(cle, t0) - t0) for cle, t0 in avant.items())
            en_cours = len({a["course"] for a in existants})
            liste.append({"id": lv["id"], "nom": lv["nom"], "base": lv["base"] or "Non définie",
                          "km": round(_km(pos_lv, pos), 1), "en_cours": en_cours, "source": source,
                          "minutes": round(minutes_nouvelle), "retard": round(retard),
                          "score": round(minutes_nouvelle + POIDS_RETARD * retard + 0.5 * en_cours, 1)})
    if not liste:
        raise LookupError("Aucun livreur disponible dont la base ou la position GPS est localisable.")
    liste.sort(key=lambda x: x["score"])
    return liste, approx


# ----------------------------------------------------------------------------- 2. itinéraire du livreur
def _lien_maps(depart, arrets):
    if not arrets:
        return ""
    points = [f"{a['pos'][0]:.6f},{a['pos'][1]:.6f}" for a in arrets]
    params = {"api": "1", "travelmode": "driving", "destination": points[-1]}
    if depart:
        params["origin"] = f"{depart[0]:.6f},{depart[1]:.6f}"
    if len(points) > 1:
        params["waypoints"] = "|".join(points[:-1][:9])
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


CORPS_ITINERAIRE = ("""
<h2 class="s" style="margin:18px 0 10px">🧭 Mon itinéraire</h2>
{% if not etapes and not sans_position %}<section class="card"><p class="vide">Aucune course à faire pour le moment. Dès qu'une commande t'est confiée, ton meilleur trajet s'affiche ici.</p></section>
{% else %}
<section class="card"><p style="margin:0 0 6px"><b>{{ etapes|length }} arrêt(s)</b> · environ <b>{{ total_km }} km</b> · <b>{{ total_min }} min</b> au total</p>
<p class="mut" style="margin:0 0 10px">Départ : {{ depart_txt }}. L'ordre ci-dessous est le plus rapide pour livrer tes clients, en récupérant toujours un colis avant de le livrer.</p>
<div style="display:flex;gap:8px;flex-wrap:wrap">{% if lien %}<a class="btn" href="{{ lien }}" target="_blank" rel="noopener">🗺️ Lancer l'itinéraire dans Maps</a>{% endif %}
<button type="button" class="btn sec" id="itiPos">📍 Partir de ma position</button></div></section>
{% for e in etapes %}<section class="card" style="display:flex;gap:12px;align-items:flex-start">
<span style="min-width:34px;height:34px;border-radius:50%;background:var(--soft);color:var(--vert);display:grid;place-items:center;font-weight:800">{{ loop.index }}</span>
<div style="flex:1"><b>{{ '📦 Récupérer' if e.type == 'P' else '🏁 Livrer' }}</b> · {{ e.numero }}<div class="mut">{{ e.lieu or 'Lieu à préciser' }}</div>
<div class="mut">≈ {{ e.km }} km · arrivée dans ~{{ e.min }} min</div></div>
<a class="btn sec" href="{{ e.maps }}" target="_blank" rel="noopener">Y aller</a></section>{% endfor %}
{% for n, quoi, lieu in sans_position %}<section class="card"><b>⚠️ {{ quoi }} · {{ n }}</b><div class="mut">{{ lieu or 'Lieu à préciser' }} : position introuvable, à placer toi-même dans ton trajet.</div></section>{% endfor %}
{% endif %}
<script>
document.getElementById('itiPos')?.addEventListener('click', function(){
  if(!navigator.geolocation){alert('Ce téléphone ne permet pas la localisation.'); return;}
  this.textContent = 'Recherche de ta position…';
  navigator.geolocation.getCurrentPosition(p => { location.href = {{ url_for('portail_livreur_itineraire')|tojson }} + '?lat=' + p.coords.latitude + '&lon=' + p.coords.longitude; },
    () => { this.textContent = '📍 Partir de ma position'; alert('Position indisponible : autorise la localisation puis réessaie.'); }, {enableHighAccuracy: true, timeout: 20000});
});
</script>
""")


@app.route("/portail-livreur/itineraire")
def portail_livreur_itineraire():
    identite, reponse = A._livreur_connecte()
    if reponse:
        return reponse
    livreur = identite["profil"]
    budget = [10]
    with A.db() as con:
        lv = con.execute("SELECT * FROM livreurs WHERE id=?", (livreur["id"],)).fetchone()
        depart, source, age = None, "", None
        try:
            lat, lon = float(request.args.get("lat", "")), float(request.args.get("lon", ""))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                depart, source = (lat, lon), "ta position actuelle"
        except ValueError:
            pass
        if not depart:
            depart, source, age = position_livreur(con, lv, budget)
            source = {"GPS": "ta dernière position partagée", "dernière course": "ta dernière collecte ou livraison",
                      "dernière position": "ta dernière position connue", "quartier de base": "ton quartier de base"}.get(source, "position inconnue")
        arrets, sans_position = courses_ouvertes(con, livreur["nom"], None, budget)
    etapes, total_km, total_min, ordre = [], 0.0, 0, []
    if arrets:
        if not depart:  # sans point de départ connu, on part du premier arrêt
            depart = arrets[0]["pos"]
            source = "premier arrêt (position inconnue)"
        ordre = meilleure_tournee(depart, arrets)
        for a, t, d in ordre:
            total_km += d
            etapes.append({"type": a["type"], "numero": a["numero"], "lieu": a["lieu"], "km": round(d, 1), "min": round(t),
                           "maps": "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=%.6f,%.6f" % a["pos"]})
        total_min = round(ordre[-1][1])
    lien = _lien_maps(depart, [a for a, _t, _d in ordre])
    return A.reponse_portail(render_template_string(PAGE_ITINERAIRE, **A._liv_ctx(
        identite, "itineraire", etapes=etapes, sans_position=sans_position, total_km=round(total_km, 1),
        total_min=total_min, lien=lien, depart_txt=source or "position inconnue")))


# ----------------------------------------------------------------------------- 3. suivi GPS économe en batterie
GPS_ECO = """
<section class="dl-gps" id="gpsBloc"><div><b>📡 Suivi en direct</b><div class="mut" id="gpsEtat">Ta position n'est pas partagée.</div></div>
<button type="button" class="btn" id="gpsBtn">Partager ma position</button></section>
<style>.dl-gps{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;background:var(--card);border:1px solid var(--bord);border-radius:16px;padding:13px 15px;margin:0 0 16px;box-shadow:var(--ombre)}.dl-gps.on{border-color:var(--vert2);background:var(--soft)}</style>
<script>
(function(){
const URL_POS = {{ url_for('portail_livreur_position')|tojson }}, CSRF = {{ csrf_portail()|tojson }};
const PAUSE = 100000; // une position toutes les ~100 secondes : le GPS ne reste jamais allumé en continu
const btn = document.getElementById('gpsBtn'), etat = document.getElementById('gpsEtat'), bloc = document.getElementById('gpsBloc');
let minuteur = null, dernier = 0;
function dire(t){etat.textContent = t;}
function envoyer(pos){
  dernier = Date.now();
  const fd = new FormData(); fd.append('_csrf', CSRF);
  fd.append('lat', pos.coords.latitude); fd.append('lon', pos.coords.longitude);
  fd.append('precision', pos.coords.accuracy || 0); fd.append('vitesse', pos.coords.speed || 0); fd.append('cap', pos.coords.heading || 0);
  fetch(URL_POS, {method: 'POST', body: fd, credentials: 'same-origin'}).then(r => r.json()).then(d => {
    dire(d.ok ? '🟢 Position partagée à ' + d.heure + ' (précision ' + Math.round(pos.coords.accuracy || 0) + ' m)' : '⚠️ Envoi refusé : reconnecte-toi.');
  }).catch(() => dire('⚠️ Pas de réseau, nouvel essai automatique…'));
}
function erreur(e){
  if(e.code === 1){dire('⛔ Autorise la localisation pour ce site dans ton navigateur, puis réessaie.'); arreter(true);}
  else dire('⚠️ GPS indisponible pour le moment, nouvel essai automatique…');
}
function lire(){
  if(document.visibilityState !== 'visible') return;
  navigator.geolocation.getCurrentPosition(envoyer, erreur, {enableHighAccuracy: true, maximumAge: 60000, timeout: 25000});
}
function demarrer(){
  if(!('geolocation' in navigator)){dire('Ce téléphone ne permet pas la localisation.'); return;}
  if(!window.isSecureContext){dire('⚠️ Le GPS ne marche que sur une adresse https (lien ngrok ou hébergement). Demande le bon lien au responsable.'); return;}
  localStorage.setItem('gps_livreur', '1');
  minuteur = setInterval(lire, PAUSE); lire();
  bloc.classList.add('on'); btn.textContent = 'Arrêter le partage'; btn.classList.add('sec'); dire('Recherche du GPS…');
}
function arreter(silencieux){
  if(minuteur) clearInterval(minuteur); minuteur = null;
  localStorage.removeItem('gps_livreur');
  bloc.classList.remove('on'); btn.textContent = 'Partager ma position'; btn.classList.remove('sec');
  if(!silencieux){const fd = new FormData(); fd.append('_csrf', CSRF); fd.append('arret', '1'); fetch(URL_POS, {method: 'POST', body: fd, credentials: 'same-origin'}); dire('Partage arrêté.');}
}
btn.addEventListener('click', () => minuteur === null ? demarrer() : arreter(false));
document.addEventListener('visibilitychange', () => { if(document.visibilityState === 'visible' && minuteur !== null && Date.now() - dernier > 30000) lire(); });
if(localStorage.getItem('gps_livreur') === '1') demarrer();
})();
</script>
<p class="mut" style="margin:-8px 0 16px">Tu n'as plus besoin de garder l'écran allumé : ta position est envoyée toutes les ~2 minutes quand l'application est ouverte, et dès que tu la rouvres. Le reste du temps, l'appli estime où tu es grâce à tes collectes et livraisons.</p>
"""

ONGLET_ITINERAIRE = ("""<a class="{{ 'on' if onglet == 'itineraire' }}" href="{{ url_for('portail_livreur_itineraire') }}"><i>🧭</i><span>Itinéraire</span></a>\n""")
ANCRE_ONGLET = """<span>Courses</span></a>\n"""


def _installer_patchs():
    """Remplace dans les gabarits déjà construits : le bloc GPS (batterie) et l'onglet Itinéraire."""
    remplaces, ancien_gps = 0, A.GPS_LIVREUR
    for nom, valeur in list(vars(A).items()):
        if not isinstance(valeur, str) or not nom.isupper():
            continue
        nouveau = valeur
        if ancien_gps in nouveau:
            nouveau = nouveau.replace(ancien_gps, GPS_ECO)
        if "<nav class=\"onglets\">" in nouveau and "portail_livreur_itineraire" not in nouveau and ANCRE_ONGLET in nouveau:
            nouveau = nouveau.replace(ANCRE_ONGLET, ANCRE_ONGLET + ONGLET_ITINERAIRE, 1)
        if nouveau != valeur:
            setattr(A, nom, nouveau)
            remplaces += 1
    return remplaces


_installer_patchs()
PAGE_ITINERAIRE = A.LIV_HAUT.replace("{{ titre }}", "Itinéraire") + CORPS_ITINERAIRE + A.LIV_BAS
A.classer_livreurs = classer_livreurs_tournee  # dispatcher() et /livreurs/suggestion appellent ce nom au moment de l'exécution
