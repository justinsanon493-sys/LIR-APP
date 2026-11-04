"""Entrypoint for local Waitress and hosted single-process deployment.

Production still uses the established root Flask app until its routes and
migrations have been moved safely into the `lir` package. This bridge ensures
that merely introducing the package does not replace the real app with
placeholder routes.
"""

import importlib
import os
import threading

import app as legacy_app
from lir import create_app

application = create_app(legacy_app.app)

legacy_app.init_db()

# Optional domain modules register routes on the legacy Flask app. Keep this
# behavior during the incremental migration.
for _module_name, _label in (("modules.services_lir", "Services"), ("modules.tournee_lir", "Tournée et assignation")):
    try:
        importlib.import_module(_module_name)
    except ModuleNotFoundError as error:
        if error.name != _module_name:
            print(f"Module {_label} non chargé : {error!r}", flush=True)
    except Exception as error:
        print(f"Module {_label} non chargé : {error!r}", flush=True)

print(f"Base de données active : {legacy_app.DB}", flush=True)
threading.Thread(target=legacy_app.boucle_relance, daemon=True).start()
threading.Thread(target=legacy_app.boucle_sauvegarde, daemon=True).start()

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
