"""Entrypoint for local Waitress and hosted single-process deployment.

Local/container start: python wsgi.py
WSGI servers may import the exported application object. Keep one process:
the background reminder and backup loops must not run in multiple workers.
"""
import threading

import app as A

A.init_db()
import importlib

# Modules optionnels (dossier modules/) : une erreur dans l'un d'eux ne doit jamais empêcher l'application de démarrer.
for _nom_module, _libelle in (("modules.services_lir", "Services"), ("modules.tournee_lir", "Tournée et assignation")):
    try:
        importlib.import_module(_nom_module)
    except ModuleNotFoundError as erreur:
        if erreur.name != _nom_module:
            print(f"Module {_libelle} non chargé : {erreur!r}", flush=True)
    except Exception as erreur:
        print(f"Module {_libelle} non chargé : {erreur!r}", flush=True)
print(f"Base de données active : {A.DB}", flush=True)
threading.Thread(target=A.boucle_relance, daemon=True).start()
threading.Thread(target=A.boucle_sauvegarde, daemon=True).start()
application = A.app

if __name__ == "__main__":
    import os

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
