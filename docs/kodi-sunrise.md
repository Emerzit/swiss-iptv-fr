# Kodi sur Raspberry Pi — URL distante et actualisation

La liste est publiée à une URL fixe. La configuration est à faire une seule fois dans **Client IPTV Simple** ; les mises à jour suivantes arrivent depuis GitHub Pages sans recopier le fichier.

## Configuration

1. Ouvrir les paramètres de **Client IPTV Simple** dans Kodi et choisir un emplacement M3U distant (`Remote path / Internet address`).
2. Renseigner :

```text
https://emerzit.github.io/swiss-iptv-fr/swiss-fr-internet.m3u
```

3. Activer l’actualisation automatique répétée (`Auto refresh mode → Repeated refresh`) avec un intervalle de **60 minutes**. Selon la version, les libellés sont traduits ou organisés différemment. Cette option désactive le cache M3U d’après la documentation de l’extension.
4. Le guide est fourni dans l’en-tête M3U (`x-tvg-url` et `url-tvg`). Si une ancienne adresse XMLTV est imposée dans les paramètres EPG, la remplacer par :

```text
https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz
```

5. Enregistrer la configuration et actualiser les chaînes, ou redémarrer l’extension. Pour une numérotation continue dans l’ordre de la liste, choisir l’option qui numérote uniquement selon l’ordre du M3U. Sinon, les tags `tvg-chno` conservent le profil de numéros configuré.

Ces options sont décrites dans la [documentation officielle IPTV Simple](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/README.md). La mise à jour du M3U et la vérification média ont été réalisées depuis le PC Sunrise ; l’interface Kodi sur votre Raspberry Pi n’a pas été observée à distance.

## Mise à jour de la source

La tâche Windows **Swiss IPTV FR - Mise a jour GitHub** lance le programme chaque jour à **12 h**, et à l’ouverture de session. Le PC doit être allumé, connecté et la session ouverte ; Codex et Kodi n’ont pas besoin d’être ouverts sur ce PC. Le programme vérifie les sources depuis Sunrise, génère les fichiers et pousse la branche publiée. GitHub Pages sert ensuite la nouvelle version à la même URL.

Le PC n’est pas un serveur vidéo. Kodi contacte directement les infrastructures des diffuseurs ou de leurs distributeurs. Quand le PC est éteint, la dernière version publiée reste accessible sur GitHub ; les nouveaux contrôles attendent la prochaine exécution.

`Mettre_a_jour.cmd` permet aussi une exécution à la demande. Les journaux restent dans `data/logs/last-update.log` et `output/audit/update.json`. Voir [publication-github.md](publication-github.md) pour la configuration et le diagnostic de la tâche.

## Sélection et guide

La sélection initiale de 54 chaînes avec image et son a été élargie automatiquement. Le [site publié](https://emerzit.github.io/swiss-iptv-fr/) donne le nombre actuel et la qualité décodée de chaque chaîne. RTS 1/2, TF1 Suisse, France 2–5, M6 Suisse et ARTE restent dans l’ordre romand demandé ; les variantes CH sont préférées et les chaînes non validées sont omises. France 24 a été améliorée vers une source Full HD. Kodi garde le choix d’une variante adaptée au matériel et au débit du foyer.

Les nombres de chaînes et de correspondances EPG de chaque fichier sont actualisés dans le [rapport public](https://emerzit.github.io/swiss-iptv-fr/status.json), afin de suivre les ajouts et retraits automatiques. La liste multicast reste vide tant qu’aucune lecture sur le réseau opérateur correspondant n’est validée.

Les correspondances EPG ne sont déclarées que si l’identifiant existe réellement dans le guide et possède des programmes futurs. Les nouveaux rapprochements par nom nécessitent une correspondance exacte et unique, sans remplacer les mappings explicites de variantes. L’exactitude éditoriale des programmes n’est pas garantie.

Les sources peuvent changer. Une panne ou un changement de droits peut réduire la liste au prochain contrôle. Les nouveaux liens et renouvellements automatiques suivent les [contrôles de provenance, d’accès et de lecture](automatisation.md). Le guide est vérifié automatiquement, tandis que l’EPG actuel reste fourni par EPGSHARE01.

Les anciens guides XMLTV.ch et XMLTV.fr restent des replis non fonctionnels au dernier contrôle (HTTP 503 et certificat TLS non conforme). Aucune validation TLS n’est désactivée. Les URL de session CDN temporaires ne sont jamais copiées dans la playlist : le lecteur utilise l’entrée publique stable pour obtenir sa propre redirection.

La version locale et le ZIP dans `output/domestic` restent disponibles pour un usage sans URL distante, mais ils ne sont pas nécessaires à la récupération automatique par Kodi.
