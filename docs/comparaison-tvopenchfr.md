# Comparaison avec tvopenchfr.m3u

Référence : [iptv-ch/tvopenchfr.m3u](https://github.com/iptv-ch/iptv-ch.github.io/blob/master/tvopenchfr.m3u). La comparaison est recalculée à chaque génération ; le [site](https://emerzit.github.io/swiss-iptv-fr/) et son [rapport JSON](https://emerzit.github.io/swiss-iptv-fr/status.json) donnent les résultats actuels.

## Résultat du contrôle du 15 novembre 2026

La référence comporte **57 entrées**, toutes multicast RTP. Le parseur strict en accepte 56 : la ligne Rhône TV est malformée. Le comparateur conserve cette ligne pour l’audit, sans l’importer comme une ligne valide, et compte bien les 57 entrées. L’en-tête XMLTV comporte également un doublon de `#EXTM3U`.

Après les recherches et lectures supplémentaires, **50 des 57 entrées** ont une chaîne correspondante dans notre sélection Internet. Les variantes publicitaires exactes ne sont pas garanties par le seul nom : TMC CH est signalée comme telle, et le multiplex LCP/Public Sénat reste distingué des services parlementaires 24h/24. Un rapprochement erroné de Canal Alpha NE dans certaines données amont est résolu par son identifiant explicite, en conservant séparément Neuchâtel et Jura.

Le total de notre sélection est supérieur, mais elle ne couvre donc pas encore toute la référence. Les nouvelles chaînes contrôlées incluent i24NEWS français, CPAC avec piste française et GONG, toutes décodées en 1920 × 1080 depuis Sunrise en Suisse. GONG publie le lecteur de son direct sur son propre site ; il n’est pas assimilé à une autorisation de reprendre un flux payant GONG MAX. Les métadonnées d’un feed multilingue ne sont pas réécrites comme « français uniquement » : un feed grec/français/anglais dont la piste française n’est pas établie est écarté, même si sa lecture technique fonctionne et qu’une ancienne décision automatique était positive.

## Entrées encore manquantes au contrôle

| Chaîne | Résultat et limite |
|---|---|
| TV5MONDE Europe | La page et les deux entrées HLS officielles examinées répondent HTTP 403 depuis le PC. La cause exacte n’est pas déduite de ce seul code. FBS reste une autre variante et ne remplace pas Europe. |
| ORTB / Bénin TV | Le site SRTB intègre publiquement le lecteur Streamakaci. Son manifeste Bénin TV est identifié, mais répond HTTP 403 lors des trois tentatives. |
| Conseil national | Le lecteur officiel français est trouvé via le domaine Simplex explicitement publié par le Parlement. Le manifeste répond HTTP 404 lors des trois tentatives du contrôle hors séance. |
| Conseil des États | Même constat HTTP 404 pour son lecteur officiel. Le service est événementiel et en langues originales ; il n’est pas exclusivement français. |
| Ici TV | Aucune source Internet linéaire et identité de service suffisamment établies. Un site ou une marque ressemblante ne suffit pas. |
| GRTV / TéléVersoix | Le site indiqué est en maintenance et aucun direct Internet n’a été validé. Cela ne démontre pas que la diffusion opérateur est arrêtée. |
| TV Onex | Le site propose les émissions et rediffusions Dailymotion. Elles ne sont pas ajoutées comme chaîne linéaire. Aucun flux Internet linéaire n’est validé. |

Les [instructions officielles du Parlement](https://www.parlament.ch/fr/services/integration-live-stream) autorisent l’intégration des débats et décrivent les langues des différents services. Elles ne prouvent pas qu’un direct est actif au moment du contrôle. Le domaine historique `live.parlament.ch` présentait un problème de certificat sur ce PC ; le lecteur `par-pcache.simplex.tv` est utilisé parce qu’il est également publié sur la page officielle, avec validation TLS conservée.

## Qualité

RTS 1 et RTS 2 sont décodées en Full HD. Les chaînes correspondantes sont testées en au moins 720p, avec les dimensions et cadences exactes dans le tableau public. Cela respecte les planchers usuels des mentions HD/FHD, sans prouver une image identique ou meilleure que le flux opérateur.

Les flux multicast de la référence n’ont pas été décodés sur un réseau compatible lors de cette comparaison. Leur résolution exacte, débit, entrelacement et qualité perceptuelle ne peuvent donc pas être comparés honnêtement. Le rapport conserve `quality_parity: not_established`. Il ne transforme pas un intitulé « HD » en mesure vidéo et ne conclut pas à une panne parce qu’une adresse multicast d’un autre réseau n’est pas recevable depuis Sunrise.

## Audio et sources supplémentaires

i24NEWS utilise un tag MPEG audio `eng`, malgré l’identification du service français dans son lecteur officiel et l’habillage français inspecté sur une image réellement décodée. Une correction est limitée à l’URL exacte, documentée par la page et son hash ; la mesure brute reste conservée. Aucune reconnaissance vocale n’est prétendue.

CPAC publie une vidéo et des pistes anglaise/française séparées. La piste française a été décodée. Le master annonce l’anglais par défaut : régler la préférence audio de Kodi sur français, ou choisir la piste française pour cette chaîne. Son nom indique le caractère bilingue. Le programme ne publie ni programmes ni manifeste vidéo modifié pour imposer une langue.

Les recherches ont aussi examiné les sites officiels et lecteurs de TV Lux, Canal Zoom et Europe by Satellite. L’absence de manifeste établi dans ces essais ne prouve pas une indisponibilité générale. Une piste supplémentaire provient de [dlq/parliament-streams](https://github.com/dlq/parliament-streams), puis a été vérifiée sur les pages et API officielles CPAC et Parlement suisse ; le dépôt communautaire ne constitue pas une autorisation de publication.
