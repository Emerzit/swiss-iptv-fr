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

La sélection initiale de 54 chaînes a été élargie automatiquement : les nombres actuels et les résolutions réellement décodées figurent sur le [site publié](https://emerzit.github.io/swiss-iptv-fr/) et dans son [rapport JSON](https://emerzit.github.io/swiss-iptv-fr/status.json). Les tests sont réalisés sur le PC Sunrise en Suisse. RTS 1/2, TF1 Suisse, France 2–5, M6 Suisse et ARTE sont conservées dans l’ordre romand. France 24 a été améliorée de 640 × 360 à 1920 × 1080. Le guide couvre au moins les 45 correspondances de la sélection initiale quand son contrôle reste valide. Ces essais courts ne garantissent pas la disponibilité continue ou tous les programmes.

## Mise à jour et publication

La tâche Windows exécute le programme **chaque jour à 12 h et à l’ouverture de session**, sous le compte utilisateur courant. Le PC doit être allumé, connecté et la session ouverte. L’exécution ne nécessite pas que Kodi ou Codex soient ouverts. Les flux arrivent directement aux lecteurs depuis les diffuseurs ou distributeurs ; le PC n’est pas un serveur vidéo.

```text
PC Sunrise : observer CH → actualiser les sources mondiales et leurs preuves
           → vérifier les chaînes et les meilleures variantes → explorer les candidates
           → appliquer les règles de provenance et d’accès → contrôler XMLTV
           → générer les fichiers → pousser la branche gh-pages
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

Le catalogue initial est reproductible depuis `data/curated-sources.yaml`. Les décisions éditoriales sont séparées dans `data/public-reviews.yaml`. La tâche importe aussi les listes francophones mondiales iptv-org, Free-TV et plusieurs listes iptv-ch, puis visite progressivement les sites des diffuseurs francophones présents dans les métadonnées. Les entrées `discovery.inputs` sont extensibles ; aucun pays étranger n’est exclu. Une nouvelle installation effectue ses propres lectures avant de générer une playlist exploitable.

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

La validation essaie les meilleures variantes HLS et représentations DASH, décode réellement la vidéo et l’audio, puis se rabat sur une variante inférieure en cas d’échec technique. Elle préfère l’audio français lorsqu’il est annoncé. Les sources éligibles sont comparées sur la résolution décodée, la cadence et le débit déclaré ; une promesse « HD » dans un M3U ne constitue pas une preuve. Les lecteurs conservent leurs possibilités d’adaptation. Les ressources DRM, les clés HLS et les URL d’authentification copiées ne sont pas traitées. Les entrées publiques stables peuvent suivre les redirections normales du CDN, sans fabrication de jeton.

Trois tentatives sont prévues, dans une enveloppe de temps bornée, avant de conclure à certaines indisponibilités. Un 403 reste un refus de cause indéterminée, un timeout ne prouve pas une panne générale et le multicast exige le réseau opérateur correspondant. La sélection Internet ne nécessite pas les flux multicast Sunrise qui ont échoué aux essais.

La publication exige une provenance, une décision positive pour le périmètre public et une lecture CH récente. Les nouveaux liens peuvent être ajoutés automatiquement après application des règles documentées : référence exacte dans un lecteur officiel, ou remplacement au sein du même service d’une chaîne déjà examinée ; flux linéaire clair, image et audio décodés en Suisse, aucun compte ni contournement. Un domaine ressemblant à celui d’un diffuseur ou une playlist communautaire ne suffit pas. Une identité ambiguë, une langue explicitement différente ou des droits non établis restent en attente. Les décisions de refus priment sur l’automatisation.

Les décisions expirent après 90 jours, les lectures après 48 h et les contrôles EPG après 24 h. Les décisions automatiques sont réévaluées sur des preuves actuelles ; la date n’est pas simplement repoussée. Une décision éditoriale publique arrivée à échéance ne peut être renouvelée que si elle satisfait à nouveau les mêmes contrôles de provenance et d’accès. La revue concerne un annuaire de liens externes, sans licence des programmes ni permission écrite de chaque titulaire. [Règles, rotation et limites](docs/automatisation.md).

Le guide CH1 d’[EPGSHARE01](https://epgshare01.online/) a des programmes futurs pour 45 chaînes de la sélection courante. Il reste fourni par ce tiers, sans copie des grilles sur GitHub. XMLTV.ch (HTTP 503) et XMLTV.fr (certificat TLS non conforme) restent des replis non fonctionnels au dernier contrôle. Aucune vérification TLS n’est désactivée.

## Développement et audit

```sh
python -m unittest discover -s tests -v
python -m swiss_iptv sync
python tools/acquire.py
python -m swiss_iptv bootstrap
python -m swiss_iptv discover
python -m swiss_iptv epg-check
python -m swiss_iptv inventory
python -m swiss_iptv report
```

La collecte élargie du 15 novembre a porté le catalogue à plus de 1 300 identités candidates. Il contient des variantes historiques, des chaînes sans flux trouvé et des droits non établis ; il ne représente pas une offre fonctionnelle de 1 300 chaînes. Le catalogue SQLite, les documents de preuve et les rapports détaillés restent locaux.

51 tests automatisés couvrent notamment les vrais décodages HLS/DASH à plusieurs résolutions, le repli après échec de la variante supérieure, l’audio séparé, la provenance, les décisions de publication autonome, le cache conditionnel et les ambiguïtés EPG. Les workflows Windows/Linux exécutent les tests. Un audit Internet quotidien GitHub garde son pays inconnu et ne publie aucune validation CH.

Voir l’[audit initial](docs/audit-phase1.md), les [résultats avant publication](docs/resultats-et-limites.md) et l’[architecture de publication](docs/publication-github.md). Le chargement de l’interface Kodi cible n’a pas été observé à distance. L’exhaustivité, l’identité de toutes les émissions et la disponibilité continue restent des limites des échantillons courts.
