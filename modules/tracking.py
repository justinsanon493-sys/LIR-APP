"""Module de suivi public de colis pour LIR Livraisons.
Permet aux clients ou destinataires de suivre leur livraison en direct avec carte interactive.
"""

def calculer_etape_suivi(statut: str) -> dict:
    """Retourne l'état d'avancement pour l'affichage visuel du tracking.
    Étapes : 
    1. Reçue (en attente)
    2. Collectée
    3. En cours de livraison
    4. Livrée
    """
    statut_clean = (statut or "").lower().strip()

    if statut_clean in ("annulé", "annule"):
        return {
            "pourcentage": 100,
            "etape_active": "annule",
            "titre": "Livraison annulée",
            "description": "Cette course a été annulée ou reportée.",
            "classe": "annule",
            "etapes": [
                {"nom": "Reçue", "icon": "📝", "statut": "done"},
                {"nom": "Annulée", "icon": "❌", "statut": "annule"}
            ]
        }

    etapes = [
        {"id": 1, "nom": "Enregistrée", "icon": "📝", "statut": "done"},
        {"id": 2, "nom": "Collectée", "icon": "📦", "statut": "todo"},
        {"id": 3, "nom": "En route", "icon": "🏍️", "statut": "todo"},
        {"id": 4, "nom": "Livrée", "icon": "✅", "statut": "todo"}
    ]

    if statut_clean == "en attente":
        pct = 25
        etapes[0]["statut"] = "done"
        etapes[1]["statut"] = "active"
        titre = "Commande confirmée"
        desc = "Notre coursier se prépare pour la collecte du colis."
    elif statut_clean in ("collecté", "collecte"):
        pct = 65
        etapes[0]["statut"] = "done"
        etapes[1]["statut"] = "done"
        etapes[2]["statut"] = "active"
        titre = "Colis en cours d'acheminement"
        desc = "Le coursier a récupéré le colis et roule vers votre adresse !"
    elif statut_clean in ("livré", "livre"):
        pct = 100
        for e in etapes:
            e["statut"] = "done"
        titre = "Colis livré avec succès !"
        desc = "La livraison a été effectuée. Merci pour votre confiance !"
    elif statut_clean in ("injoignable", "reporté", "reporte"):
        pct = 50
        etapes[0]["statut"] = "done"
        etapes[1]["statut"] = "done"
        etapes[2]["statut"] = "active"
        titre = "Destinataire injoignable"
        desc = "Le coursier est sur place et tente de vous joindre."
    else:
        pct = 25
        titre = "En cours de traitement"
        desc = "Votre livraison est prise en charge par notre équipe."

    return {
        "pourcentage": pct,
        "titre": titre,
        "description": desc,
        "etapes": etapes
    }

TEMPLATE_SUIVI_PUBLIC = """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Suivi Colis {{ numero }} — LIR Express</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='modern_ui.css') }}">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body {
      background: #f4f7f5;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0;
      padding: 16px 12px 60px;
      color: #111e16;
    }
    .suivi-card {
      max-width: 600px;
      margin: 16px auto;
      background: #fff;
      border-radius: 24px;
      padding: 28px 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.06);
      border: 1px solid #e2ece5;
    }
    .suivi-logo {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 800;
      font-size: 1.35rem;
      color: #0b7a3b;
      margin-bottom: 20px;
    }
    .badge-num {
      background: rgba(11, 122, 59, 0.1);
      color: #0b7a3b;
      padding: 6px 14px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 0.95rem;
      display: inline-block;
    }
    #carte-live {
      height: 270px;
      width: 100%;
      border-radius: 18px;
      margin: 20px 0;
      border: 1px solid #cadcd0;
      box-shadow: inset 0 2px 6px rgba(0,0,0,0.05);
      z-index: 10;
    }
    .badge-live-gps {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: rgba(16, 185, 129, 0.12);
      color: #047857;
      padding: 4px 12px;
      border-radius: 999px;
      font-size: 0.8rem;
      font-weight: 700;
      margin-top: 8px;
    }
    .badge-live-gps::before {
      content: '';
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      animation: pulse 1.8s infinite;
    }
    .dest-box {
      background: #f9fbf9;
      border: 1px solid #e1ebe3;
      border-radius: 16px;
      padding: 16px 18px;
      margin: 20px 0;
      text-align: left;
    }
    .dest-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
      font-size: 0.93rem;
    }
    .dest-row:last-child { margin-bottom: 0; }
    .dest-label { color: #62776b; font-weight: 500; }
    .dest-val { font-weight: 700; color: #111e16; }
  </style>
</head>
<body>
  <div class="suivi-card">
    <div class="suivi-logo">
      <span>🏍️</span> LIR Livraisons Express
    </div>

    <div>
      <span class="badge-num">{{ numero }}</span>
      <h2 style="margin: 14px 0 6px; font-size: 1.4rem; letter-spacing: -0.02em;">{{ suivi.titre }}</h2>
      <p style="color: #62776b; margin: 0 0 20px; font-size: 0.93rem;">{{ suivi.description }}</p>
    </div>

    <!-- Barre d'avancement -->
    <div class="tracking-steps">
      <div class="tracking-progress-line" style="width: {{ suivi.pourcentage }}%;"></div>
      {% for e in suivi.etapes %}
      <div class="tracking-step {{ e.statut }}">
        <div class="step-icon">{{ e.icon }}</div>
        <span class="step-title">{{ e.nom }}</span>
      </div>
      {% endfor %}
    </div>

    <!-- Carte interactive si coordonnées disponibles -->
    {% if pos_livreur or pos_dest %}
    <div>
      {% if pos_livreur %}
      <div class="badge-live-gps">Position du coursier en direct 🛰️</div>
      {% endif %}
      <div id="carte-live"></div>
    </div>
    {% endif %}

    <!-- Détails de la course -->
    <div class="dest-box">
      <div class="dest-row">
        <span class="dest-label">Destinataire</span>
        <span class="dest-val">{{ livraison.destinataire_nom or 'Client' }}</span>
      </div>
      <div class="dest-row">
        <span class="dest-label">Lieu de livraison</span>
        <span class="dest-val">📍 {{ livraison.livraison_quartier or livraison.livraison_adresse or 'Ouagadougou' }}</span>
      </div>
      <div class="dest-row">
        <span class="dest-label">Colis</span>
        <span class="dest-val">📦 {{ livraison.colis or 'Colis' }}</span>
      </div>
      {% if livraison.livreur %}
      <div class="dest-row" style="margin-top: 10px; padding-top: 10px; border-top: 1px dashed #cadcd0;">
        <span class="dest-label">Livreur assigné</span>
        <span class="dest-val" style="color:#0b7a3b;">🏍️ {{ livraison.livreur }}</span>
      </div>
      {% endif %}
    </div>

    <p style="font-size: 0.8rem; color: #8fa196; margin-top: 24px; text-align: center;">
      Mise à jour en direct • LIR Ouagadougou
    </p>
  </div>

  {% if pos_livreur or pos_dest %}
  <script>
    document.addEventListener("DOMContentLoaded", function() {
      const posLivreur = {{ pos_livreur|tojson if pos_livreur else 'null' }};
      const posDest = {{ pos_dest|tojson if pos_dest else 'null' }};

      const centre = posLivreur || posDest || [12.3714, -1.5197]; // Ouaga centre
      const map = L.map('carte-live').setView([centre[0], centre[1]], 13);

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '© OpenStreetMap'
      }).addTo(map);

      const markers = [];

      if (posDest) {
        const destIcon = L.divIcon({
          html: '<div style="font-size:24px;filter:drop-shadow(0 2px 4px rgba(0,0,0,0.3));">🏁</div>',
          className: 'custom-icon',
          iconSize: [28, 28],
          iconAnchor: [14, 28]
        });
        const mDest = L.marker([posDest[0], posDest[1]], {icon: destIcon})
          .addTo(map)
          .bindPopup('<b>Destination</b><br>{{ livraison.livraison_quartier or "Livraison" }}');
        markers.push(mDest);
      }

      if (posLivreur) {
        const bikeIcon = L.divIcon({
          html: '<div style="font-size:28px;filter:drop-shadow(0 3px 6px rgba(0,0,0,0.35));">🏍️</div>',
          className: 'custom-icon',
          iconSize: [32, 32],
          iconAnchor: [16, 28]
        });
        const mBike = L.marker([posLivreur[0], posLivreur[1]], {icon: bikeIcon})
          .addTo(map)
          .bindPopup('<b>Livreur : {{ livraison.livreur }}</b><br>En route vers vous');
        markers.push(mBike);
      }

      if (markers.length > 1) {
        const group = new L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.25));
      }
    });
  </script>
  {% endif %}
</body>
</html>
"""
