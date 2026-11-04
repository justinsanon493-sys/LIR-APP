# LIR Android

Cette application ouvre LIR dans une fenêtre Android sans barre d'adresse. Elle ne contient aucune base de données métier : l'application Flask reste le serveur LIR.

## Construire une version locale

Installe Android Studio avec Android SDK 36 et un JDK 17. Depuis ce dossier, construis une APK de test pour le réseau local :

```powershell
gradle assembleDebug -PlirUrl=http://ADRESSE_IP_DU_PC:5001
```

Le téléphone et le PC doivent être sur le même Wi-Fi. Cette version locale ne doit pas être publiée.

## Construire la version Google Play

Après la mise en ligne HTTPS de LIR :

```powershell
gradle bundleRelease -PlirUrl=https://votre-domaine
```

Le fichier `.aab` est généré dans `app/build/outputs/bundle/release/`. Crée et conserve la clé de signature hors du dépôt ; elle est indispensable pour les mises à jour futures.

## Informations Play Store à préparer

- Nom public : LIR
- Identifiant Android : `bf.lir.livraisons`
- Adresse de confidentialité : `https://votre-domaine/confidentialite`
- Accès de test Play Console si l'administration nécessite un mot de passe
- Captures d'écran Android, icône haute résolution et adresse e-mail de support
