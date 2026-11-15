# Collecte autonome et choix de qualité

Le point d’entrée est `python tools/update.py`. La tâche Windows déjà installée l’exécute à l’ouverture de session et à midi. Le PC Sunrise effectue les contrôles suisses ; GitHub Pages conserve les fichiers lorsque ce PC est éteint. Kodi utilise toujours la même URL distante.

## Cycle

1. Observer le pays de sortie et arrêter si ce n’est pas CH.
2. Charger le catalogue initial et les décisions explicites. Un refus récent ne peut être effacé par une ancienne approbation livrée avec le projet.
3. Actualiser les métadonnées iptv-org, la liste mondiale en français, Free-TV et plusieurs listes iptv-ch. ETag/Last-Modified évitent les téléchargements inutiles. Les octets téléchargés sont conservés compressés, datés et identifiés par SHA-256. Un cache corrompu n’est pas présenté comme une preuve téléchargée.
4. Rafraîchir une source principale par chaîne, en conservant la préférence de qualité connue même après une extinction prolongée du PC. Les chaînes dont le contrôle est le plus ancien passent d’abord ; les alternatives approuvées servent de repli si la principale échoue. Une lecture de meilleure qualité datant de moins de 20 h sur le même contexte peut être réutilisée.
5. Visiter une partie des pages officielles et explorer des alternatives, en conservant les dates des tentatives dans SQLite. Le nombre de candidates n’est pas plafonné. Le budget de chaque exécution limite les requêtes ; la rotation reprend ensuite les éléments restants. Les pays voisins ont une priorité de visite, sans exclusion des autres pays.
6. Prendre une décision de publication seulement si les règles ci-dessous sont satisfaites. Vérifier XMLTV, générer les cinq M3U, les mesures de qualité et le bilan des changements, puis publier uniquement les fichiers statiques autorisés.

Les sources et leur provenance restent dans SQLite. `output/audit/update.json`, `data/evidence/autonomy/exploration.json` et `data/logs/last-update.log` décrivent le dernier cycle. Le rapport public `status.json` contient les chaînes retenues, leur résolution décodée, cadence, codecs, date de lecture et les changements de sélection. La comparaison de référence est recalculée à chaque export ; ses chaînes manquantes deviennent des priorités de découverte tout en conservant les délais entre tentatives.

## Conditions d’un ajout automatique

Une liste communautaire fournit une piste. Elle ne constitue pas une autorisation de diffusion et le champ « official » ne suffit pas à lui seul.

Deux chemins permettent une décision :

- Une référence exacte et datée au manifeste dans une page ou un lecteur officiel de la chaîne, y compris une configuration publique explicitement chargée par ce lecteur. Un hébergement partagé n’est accepté qu’à travers cette référence. Une page générique présentant plusieurs flux non attribuables reste ambiguë.
- Une URL de remplacement dans le même service d’une chaîne déjà examinée. Les règles sont bornées : même chaîne et identifiant de service Netplus, service français France 24, ou chemin exact de service Infomaniak reconnu. Aucune règle n’approuve tout un CDN.

Un domaine de flux correspondant au site déclaré dans les métadonnées n’est qu’une piste : le collecteur cherche encore une référence dans le lecteur public avant de créer une décision.

Dans les deux cas, l’URL stable doit avoir une provenance actuelle et réussir une lecture CH avec vidéo et audio. Le manifeste doit être linéaire et clair, sans fin de fichier VOD. Une langue audio explicitement étrangère bloque l’ajout ; lorsque la piste est sans étiquette, la langue française repose sur l’identité du feed, sans prétendre reconnaître la parole. Les comptes, clés HLS, DRM, paramètres d’authentification copiés, sessions publiables et chaînes payantes identifiées sont exclus. Un refus ou une attente éditoriale explicite, ainsi qu’un périmètre domestique, priment sur la politique automatique.

Chaque nouvelle décision conserve le nom de la règle, la preuve et son hash, le test concerné et sa justification. Le renouvellement repose sur des éléments actuels, avec lecture réussie ; une ancienne date n’est pas simplement remplacée. Les décisions expirent après 90 jours, les lectures après 48 h, les contrôles EPG après 24 h.

Il s’agit d’un annuaire de liens externes, sans lecteur embarqué, copie des programmes ou licence sur les contenus. Les conditions des diffuseurs restent applicables. Une demande de retrait ou un changement des droits doit être traduit en décision explicite ou en exclusion ; le programme ne peut découvrir automatiquement toutes les évolutions contractuelles.

## Mesure de qualité

Le vérificateur examine les variantes HLS et représentations DASH, privilégie la résolution puis la cadence, et essaie réellement le décodage. Il évite les variantes uniquement audio et choisit une piste française lorsqu’elle est annoncée. Un échec technique de la meilleure variante permet un essai inférieur, sans contourner un refus d’accès. Les sources éligibles sont comparées sur les dimensions décodées, la cadence et le débit déclaré ; la priorité et la provenance départagent les résultats comparables.

Le lien du manifeste adaptatif reste dans le M3U : Kodi peut choisir une variante compatible avec son matériel et le débit du foyer. Une résolution supérieure ne garantit pas une meilleure image perceptuelle, un débit constant, ou un décodage matériel sur chaque modèle de Raspberry Pi. Le rapport distingue les dimensions lues du débit seulement annoncé par le manifeste.

Les valeurs par défaut bornent le contrôle à trois tentatives et 100 secondes par source, six variantes par tentative, seize minutes pour les principales et dix-huit minutes pour l’exploration. Les requêtes sont espacées. Ces valeurs sont ajustables dans `config.yaml` ; elles limitent le travail par cycle, pas le catalogue.

## Sources et lecteurs

`discovery.inputs` accepte d’autres playlists M3U/M3U8 publiques avec une URL de provenance. `python -m swiss_iptv sync` actualise les données sans accorder de droits. Les sites des diffuseurs francophones sont visités progressivement même lorsqu’aucun flux n’est encore connu. Les pages configurées peuvent préciser le lecteur ou le service pour éviter les confusions entre chaînes et variantes régionales.

La découverte traite les pages, scripts ciblés, liens vers le direct, iframes publiques Infomaniak et configurations JSON de lecteurs. Quelques pages peuvent être rendues avec Obscura s’il est disponible au chemin configuré. Aucun profil de connexion n’est fourni et les options de furtivité, extraction de cookies et accès aux réseaux privés ne sont pas activées. La collecte reste fonctionnelle sans ce binaire, notamment sur Linux.

Les répertoires professionnels [Locales.tv](https://locales.tv/chaines-adherents/), le [réseau belge des médias de proximité](https://www.mediasdeproximite.be/nos-medias-regionaux/matele/) et les [informations du CSA belge](https://www.csa.be/service/matele/) ont aussi servi à vérifier les identités lors de l’élargissement initial. Les [conditions Monaco Info](https://monacoinfo.com/cgu/) distinguent l’accès au direct et les droits des contenus, et prévoient la création de liens externes. Ces références ne sont pas des autorisations générales de redistribution des vidéos.

## Limites

Le système explore un ensemble extensible de sources et de sites ; il ne prétend pas parcourir tout Internet ni prouver une exhaustivité mondiale. Les lecteurs opaques, les sources à jetons temporaires, les variantes linguistiques ambiguës ou les droits non établis peuvent rester en attente. Les échantillons courts ne garantissent ni toutes les émissions ni une disponibilité permanente. Les liens et métadonnées de tiers peuvent disparaître ; la rotation et les sources alternatives réduisent cette dépendance sans l’abolir.

L’audit quotidien GitHub est distinct des lectures CH et ne publie pas de validation suisse. Le multicast n’est jamais testé comme une ressource Internet : il exige un réseau opérateur explicitement compatible.
