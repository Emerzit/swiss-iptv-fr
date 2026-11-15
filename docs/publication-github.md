# Publication GitHub et actualisation automatique

Le dépôt cible est [Emerzit/swiss-iptv-fr](https://github.com/Emerzit/swiss-iptv-fr). Le code est sur `main` et les seuls fichiers statiques destinés à Kodi sur `gh-pages`. GitHub Pages sert cette branche à l’adresse `https://emerzit.github.io/swiss-iptv-fr/`.

## Fonctionnement

`tools/update.py` observe le pays de la connexion, exige CH, restaure le catalogue initial et actualise les sources publiques avec cache HTTP conditionnel. Il vérifie les meilleures variantes des chaînes connues, explore les sites officiels et sources alternatives par rotation, applique les règles d’accès, contrôle XMLTV et génère les cinq M3U. Les nouveaux liens sont publiés uniquement après provenance contrôlée et lecture réelle en Suisse. Voir [automatisation.md](automatisation.md).

Lorsque `data/github.local.yaml` active la publication, `swiss_iptv/remote.py` valide tous les fichiers avant de contacter GitHub. Il contrôle le périmètre public, la fraîcheur de la génération, les en-têtes et nombres de chaînes et refuse les sessions temporaires. Il construit une arborescence Git à partir d’une liste fixe : cinq M3U, `index.html`, `status.json` et `.nojekyll`.

Le cache Git de publication reste sous `data/pages.git`, sans checkout du code distant. Les commits suivent l’historique de `gh-pages` et sont poussés sans force. Une modification concurrente est relue une fois ; un échec Git laisse la version déjà en ligne inchangée. La base SQLite, les sessions, les preuves vidéo et les rapports locaux ne peuvent pas être ajoutés à l’arborescence publiée par ce mécanisme.

La configuration Pages publie automatiquement la branche. Les URL des fichiers restent stables, par exemple :

```text
https://emerzit.github.io/swiss-iptv-fr/swiss-fr-internet.m3u
https://emerzit.github.io/swiss-iptv-fr/status.json
```

## Planification sur Windows

`tools/install_scheduled_task.ps1` enregistre **Swiss IPTV FR - Mise a jour GitHub** sous l’utilisateur courant, avec des privilèges limités. Déclenchements : tous les jours à 12 h, et à l’ouverture de session. Le programme utilise Python sans fenêtre, journalise localement, puis se termine. Il n’ouvre aucun port réseau et n’installe aucun serveur ou runner permanent.

Le PC doit être allumé, connecté et la session ouverte pour les vérifications. Le déclenchement de connexion permet de rattraper une extinction à l’heure habituelle. Les lecteurs continuent d’accéder à la version publiée lorsque le PC est éteint. Le programme ne prétend pas actualiser une vérification suisse lorsque le PC n’est pas disponible ou que la connexion est signalée hors CH.

```powershell
Get-ScheduledTask -TaskName 'Swiss IPTV FR - Mise a jour GitHub'
Get-ScheduledTaskInfo -TaskName 'Swiss IPTV FR - Mise a jour GitHub'
Start-ScheduledTask -TaskName 'Swiss IPTV FR - Mise a jour GitHub'
```

Consulter `data/logs/last-update.log` et `output/audit/update.json` pour le résultat. `Mettre_a_jour.cmd` permet aussi une exécution manuelle. Un verrou système associé à `data/update.lock` empêche les exécutions simultanées. Le système le libère même si le processus est interrompu ; le fichier peut rester présent sans qu’une mise à jour soit en cours. Ne pas supprimer le fichier pour contourner un verrou actif.

## Authentification et déploiement initial

Le script `tools/github_setup.py` utilise l’authentification déjà fournie par Git Credential Manager, uniquement auprès de `api.github.com`, sans afficher ni sauvegarder de jeton. Il refuse un compte différent du propriétaire demandé et un dépôt existant non identifié comme ce projet. Il crée le dépôt public ou active Pages sur `gh-pages` selon l’option fournie.

Le compte doit disposer de ses droits GitHub habituels. L’envoi périodique utilise HTTPS et le gestionnaire d’identifiants de Git, sans saisie interactive. Si l’authentification doit être renouvelée, l’exécution échoue dans le journal ; aucun identifiant n’est placé dans l’URL de Kodi.

Obscura a été téléchargé depuis sa version officielle v0.2.7, avec contrôle SHA-256 de l’archive Windows, et utilisé pour les vérifications GitHub et du site hébergé. Son binaire reste dans `tools/bin`, ignoré par Git. Le collecteur peut aussi l’utiliser pour rendre quelques pages publiques JavaScript par exécution, sans profil utilisateur, extraction de cookies, mode furtif ou accès aux réseaux privés. Son absence laisse fonctionner la collecte HTTP classique. L’authentification Git utilise son gestionnaire d’identifiants habituel.

## Revue des liens et limites

La publication externe a fait l’objet de décisions distinctes dans `data/public-reviews.yaml`. Le fondement examiné distingue l’annuaire de liens clairement externes de l’incorporation de contenus. Le site n’embarque aucun lecteur et ne contient ni vidéos, ni images des logos, ni programmes XMLTV copiés. Les liens dirigent vers les infrastructures des diffuseurs ou de leurs distributeurs.

Cette revue ne constitue pas une permission écrite de chaque titulaire ni une certification juridique universelle. Les conditions des sources restent applicables. Chaque URL a sa décision et sa preuve de lecture CH/Sunrise. Le moteur peut prendre une nouvelle décision selon les règles de provenance, de service et d’accès décrites dans `swiss_iptv/autonomy.py` ; il ne peut promouvoir une attente explicite, un refus ou une décision domestique. Les preuves de lecture expirent après 48 h et les décisions après 90 jours. Un renouvellement nécessite des éléments actuels et un test réussi ; une date seule ne suffit pas.

Le guide reste fourni par EPGSHARE01 ; seule son URL est publiée, sans copie des programmes. Le chargement réel dans votre Kodi n’a pas été observé à distance. Kodi doit être configuré une seule fois avec une URL distante et une actualisation périodique pour récupérer les versions suivantes.
