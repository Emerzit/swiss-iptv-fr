# Swiss IPTV FR

Catalogue et vérification de chaînes francophones pour une réception personnelle en Suisse, avec une URL M3U fixe sur GitHub Pages. Le code original est sous MIT ; les droits des programmes, marques, logos, guides et données de tiers restent à leurs titulaires (voir [NOTICE.md](NOTICE.md)).

## Utilisation dans Kodi

Configurer une seule fois **Client IPTV Simple** avec cette liste M3U distante :

```text
https://emerzit.github.io/swiss-iptv-fr/swiss-fr-internet.m3u
```

Activer son actualisation périodique, par exemple chaque heure. Le lien du guide est intégré dans le M3U. Si Kodi possède déjà un autre guide imposé, le remplacer par :

```text
https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz
```

Les mises à jour de la playlist sont ensuite récupérées à la même URL. [Instructions Kodi](docs/kodi-sunrise.md) · [Site et fichiers](https://emerzit.github.io/swiss-iptv-fr/) · [Dépôt](https://github.com/Emerzit/swiss-iptv-fr).

La sélection du 15 novembre 2026 contient **54 chaînes réellement testées avec image et son sur le PC Sunrise en Suisse**, dont RTS 1/2, TF1 Suisse, France 2–5, M6 Suisse et ARTE. Le guide couvre **45 chaînes**. RTS 1 et RTS 2 ont aussi été décodées quinze secondes en Full HD avec audio français. Ces essais ponctuels ne garantissent pas la disponibilité continue ou tous les programmes.

## Mise à jour et publication

La tâche Windows exécute le programme **chaque jour à 12 h et à l’ouverture de session**, sous le compte utilisateur courant. Le PC doit être allumé, connecté et la session ouverte. L’exécution ne nécessite pas que Kodi ou Codex soient ouverts. Les flux arrivent directement aux lecteurs depuis les diffuseurs ou distributeurs ; le PC n’est pas un serveur vidéo.

```text
PC Sunrise : observer le pays CH → vérifier les sources approuvées → vérifier XMLTV
           → générer les fichiers publics → pousser la branche gh-pages
GitHub Pages : publier automatiquement la branche → Kodi relit la même URL
```

Un contrôle depuis un runner GitHub étranger n’est pas étiqueté CH. Le programme n’installe pas de runner permanent sur le PC. Il s’exécute localement pendant la mise à jour, puis se termine. Le démarrage de la tâche permet de rattraper un PC éteint à l’heure habituelle. La version déjà publiée reste accessible quand le PC est éteint.

Pour lancer aussi une mise à jour à la demande : **`Mettre_a_jour.cmd`**, ou :

```powershell
python tools/update.py
```

La tâche utilise `tools/scheduled_update.py` et écrit `data/logs/last-update.log`. Son résultat et le commit publié sont enregistrés dans `output/audit/update.json`. Les URL temporaires de session CDN sont masquées dans les journaux et ne sont jamais écrites dans les playlists.

[Installation et architecture de publication](docs/publication-github.md).

## Fichiers proposés

| Playlist | Contenu |
|---|---|
| `swiss-fr.m3u` | Une source éligible par chaîne |
| `swiss-fr-internet.m3u` | Sources Internet retenues |
| `swiss-fr-multicast.m3u` | Sources multicast validées sur leur réseau opérateur (actuellement aucune) |
| `swiss-fr-regional.m3u` | Télévisions régionales suisses |
| `swiss-fr-news.m3u` | Chaînes d’information |

Le profil de `config.yaml` place RTS 1/2, TF1 Suisse et les grandes généralistes en tête, puis les autres familles, dans un ordre inspiré de la référence transmise. Les identifiants restent stables, les variantes CH sont préférées par emplacement, les numéros `tvg-chno` et les noms sont personnalisables. Les logos restent des références externes ; ils ne sont pas réhébergés.

## Installation du programme

Python 3.11+, Git, PyYAML et FFmpeg. SQLite est fourni avec Python. FFprobe n’est pas requis : FFmpeg analyse les flux et décode la vidéo et l’audio.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install .
# Fournir FFmpeg dans le PATH ; autre solution :
python -m pip install imageio-ffmpeg
```

Sous Debian/Raspberry Pi OS, si l’on souhaite exécuter les scripts ailleurs : installer `python3-venv`, `git` et `ffmpeg`, créer un environnement virtuel et exécuter `python -m pip install .`. Dans l’installation décrite ici, **tous les tests sont effectués sur le PC et le Raspberry Pi sert uniquement de lecteur Kodi**.

Le catalogue retenu est reproductible depuis `data/curated-sources.yaml`, qui contient les métadonnées, les URL exactes et leur provenance. Le chargement de ce fichier n’approuve aucun lien. Les décisions éditoriales sont séparées dans `data/public-reviews.yaml`. Une nouvelle installation effectue ses propres lectures avant de générer une playlist exploitable.

Pour activer un dépôt personnel avec l’authentification Git déjà enregistrée :

```powershell
Copy-Item data/local-profile.example.yaml data/local-profile.yaml
# Adapter isp au fournisseur réel avant les tests.
python tools/github_setup.py --owner VOTRE_COMPTE --name swiss-iptv-fr
python tools/update.py
python tools/github_setup.py --owner VOTRE_COMPTE --name swiss-iptv-fr --pages
powershell -File tools/install_scheduled_task.ps1
```

Le propriétaire doit correspondre au compte authentifié. Aucun jeton n’est écrit dans les scripts ou fichiers YAML ; Git utilise son gestionnaire d’identifiants. Le réglage local `data/github.local.yaml` est ignoré par Git. Configurer ensuite Kodi avec l’URL du nouveau compte.

## Contrôles et périmètre

La validation analyse les manifestes HLS/DASH puis effectue un vrai décodage, y compris les groupes audio HLS séparés. Le choix vidéo évite les variantes uniquement audio à faible débit. Les ressources DRM, les clés HLS et les URL d’authentification copiées ne sont pas traitées. Les entrées publiques stables peuvent suivre les redirections normales du CDN, sans fabrication de jeton.

Trois tentatives sont prévues avant de conclure à certaines indisponibilités. Un 403 reste un refus de cause indéterminée, un timeout ne prouve pas une panne générale et le multicast exige le réseau opérateur correspondant. Les 54 chaînes Internet ne nécessitent pas les flux multicast Sunrise qui ont échoué aux essais.

La publication exige une provenance, une revue positive pour le périmètre public et une lecture CH récente. Les liens nouveaux ne sont jamais approuvés par la découverte ou la tâche quotidienne. Les revues restent limitées à 90 jours, les lectures à 48 h et les contrôles EPG à 24 h ; un changement de droits ou de source peut nécessiter une nouvelle revue. La revue publique concerne l’annuaire de liens externes et ne constitue pas une licence des programmes ou une permission écrite des titulaires. Aucun lecteur vidéo n’est embarqué sur le site.

Le guide CH1 d’[EPGSHARE01](https://epgshare01.online/) a des programmes futurs pour 45 chaînes de la sélection courante. Il reste fourni par ce tiers, sans copie des grilles sur GitHub. XMLTV.ch (HTTP 503) et XMLTV.fr (certificat TLS non conforme) restent des replis non fonctionnels au dernier contrôle. Aucune vérification TLS n’est désactivée.

## Développement et audit

```sh
python -m unittest discover -s tests -v
python tools/acquire.py
python -m swiss_iptv bootstrap
python -m swiss_iptv discover
python -m swiss_iptv epg-check
python -m swiss_iptv inventory
python -m swiss_iptv report
```

L’audit large a recensé 520 identités candidates et 909 sources avant la publication. Ce vivier contient des variantes historiques et des droits non établis ; il n’est pas publié comme une offre fonctionnelle. Le catalogue SQLite, les documents de preuve, les sessions et les rapports détaillés restent locaux.

40 tests automatisés couvrent notamment les vrais décodages HLS/DASH synthétiques, l’audio séparé, les variantes suisses, l’expiration des contrôles, le filtrage privé/public et une publication Git réelle vers un dépôt temporaire. Les workflows Windows/Linux exécutent les tests ; les audits Internet GitHub ne remplacent pas les contrôles CH.

Voir l’[audit initial](docs/audit-phase1.md), les [résultats avant publication](docs/resultats-et-limites.md) et l’[architecture de publication](docs/publication-github.md). Le chargement de l’interface Kodi cible n’a pas été observé à distance. L’exhaustivité, l’identité de toutes les émissions et la disponibilité continue restent des limites des échantillons courts.
