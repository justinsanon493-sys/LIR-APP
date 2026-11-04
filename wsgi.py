"""Entrypoint for local Waitress and hosted single-process deployment.

This keeps the project structured around the new `lir` package while still
being compatible with the legacy `app.py` business logic and optional modules.
"""

import importlib
import os
import threading

from lir import create_app

app = create_app()

# Compatibility layer: if the legacy application exists, keep its initialization
# and long-running loops. This is deliberately optional so the refactor can be
# incremental without breaking startup.
try:
    import app as legacy_app  # noqa: F401
except Exception:  # pragma: no cover - legacy app may be absent during migration
    legacy_app = None

if legacy_app is not None:
    try:
        legacy_app.init_db()
    except Exception as exc:  # pragma: no cover
        print(f"Legacy init_db() non disponible ou invalide : {exc!r}", flush=True)

    for _nom_module, _libelle in (("modules.services_lir", "Services"), ("modules.tournee_lir", "Tournée et assignation")):
        try:
            importlib.import_module(_nom_module)
        except ModuleNotFoundError as erreur:
            if erreur.name != _nom_module:
                print(f"Module {_libelle} non chargé : {erreur!r}", flush=True)
        except Exception as erreur:
            print(f"Module {_libelle} non chargé : {erreur!r}", flush=True)

    db_name = getattr(legacy_app, "DB", None) or getattr(legacy_app, "db", None)
    print(f"Base de données active : {db_name}", flush=True)

    if hasattr(legacy_app, "boucle_relance"):
        threading.Thread(target=legacy_app.boucle_relance, daemon=True).start()
    if hasattr(legacy_app, "boucle_sauvegarde"):
        threading.Thread(target=legacy_app.boucle_sauvegarde, daemon=True).start()

application = app

if __name__ == "__main__":
    host = "0.0.0.0"
    port = max(1, int(os.environ.get("PORT", "5001")))
    try:
        from waitress import serve
    except ImportError:
        print("Waitress absent : Flask demarre en mode de secours. Installe-le avec python -m pip install waitress.", flush=True)
        application.run(host=host, port=port, debug=False, use_reloader=False)
    else:
        print(f"Serveur Waitress actif sur http://localhost:{port}", flush=True)
        serve(application, host=host, port=port, threads=8)
