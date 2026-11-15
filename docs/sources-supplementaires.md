# Recherche complémentaire du 15 novembre 2026

Le catalogue contient 1 367 identités candidates francophones et 1 137 sites distincts renseignés. Ces nombres comprennent des chaînes historiques, des doublons de variantes et des services payants : ils ne constituent pas une offre exploitable. L'exploration reste progressive. Au début de ce contrôle complémentaire, 156 pages de chaînes et 137 sources distinctes avaient fait l'objet de contrôles ; la recherche n'était donc pas exhaustive.

## Ajouts validés depuis Sunrise en Suisse

Chaque ajout possède une référence exacte dans son lecteur public officiel et un décodage réel de cinq secondes de vidéo et d'audio. Les maîtres stables sont publiés ; les adresses temporaires des segments et sessions CDN ne le sont pas.

| Chaîne | Provenance officielle | Décodage du 15 novembre | Résultat |
|---|---|---|---|
| HANDICAP TV | [Lecteur public](https://www.handicaptv.fr/) | 1920 × 1080, 30 i/s, H.264 / AAC | Ajoutée |
| TV Découverte | [Direct officiel](https://tvdecouverte.ch/live/) et configuration Infomaniak référencée | 1920 × 1080, 25 i/s, H.264 / AAC | Ajoutée aux chaînes et aux régionales suisses |
| Tébéo | [Direct officiel](https://www.tebeo.bzh/direct/) et script de lecteur Blastream explicitement chargé par cette page | 1920 × 1080, 25 i/s, H.264 / AAC | Ajoutée |

La sélection passe de 63 à 66 chaînes lors de ce contrôle. Les trois sources sont renseignées en français et ne signalent pas de langue audio différente ; l'absence de tag audio ne constitue pas une reconnaissance de la langue parlée de chaque émission. La meilleure variante annoncée a été décodée pour TV Découverte et Tébéo. HANDICAP TV propose une playlist média sans variantes supérieures annoncées. Ces échantillons ne garantissent pas une disponibilité permanente ni la meilleure qualité perceptuelle de toutes les sources possibles.

## Pistes examinées mais non publiées

| Chaîne | Constat |
|---|---|
| TV7 Colmar | Le [lecteur officiel](https://www.tv7.fr/Direct.html) fournit un DASH clair et stable ; décodage réussi en 1280 × 720, 25 i/s. Sa piste est explicitement marquée `eng`. Une possible erreur de métadonnées reste à résoudre : pas d'ajout automatique comme chaîne française. |
| Vosges TV | Le [lecteur officiel](https://www.viavosges.tv/Direct.html) fournit un DASH clair et stable ; décodage réussi en 720 × 576, 25 i/s. Même réserve sur le tag audio `eng`. Le résultat SD mesuré n'est pas remplacé par la promesse HD du site. |
| NRJ Hits | Le [lecteur officiel](https://www.nrj.fr/nrj-hits) demande une connexion de compte. Le HLS examiné répond aussi HTTP 403 lors de trois tentatives. Une restriction de compte explicite bloque la publication même si une URL répondait ultérieurement. |
| TVcom | Le [direct officiel](https://www.tvcom.be/direct) utilise un lecteur Freecaster chargé par l'application du site. Aucune URL stable avec provenance suffisante n'est établie dans cet essai ; cela ne démontre pas une panne de la chaîne. |
| Télé Gohelle, viàOccitanie | Aucune référence de manifeste public stable validée dans les pages examinées. |
| viàTéléPaese | Le domaine historique examiné affiche désormais des contenus sur les casinos. Une suspension explicite évite de prendre ce domaine pour une preuve actuelle de contrôle du diffuseur. |

Les adaptations du logiciel suivent les scripts publics chargés par affectation littérale `script.src`, ainsi que la configuration publique `live1` du lecteur HDR VISIO sur le même site. Elles n'utilisent ni compte, ni clé DRM, ni jeton extrait d'une session privée. Les sources communautaires servent de pistes ; elles ne suffisent pas à autoriser une publication.

La comparaison avec `tvopenchfr.m3u` reste de 50 chaînes couvertes sur 57. Les trois ajouts sont des services supplémentaires ; ils ne résolvent pas les sept écarts documentés dans [la comparaison](comparaison-tvopenchfr.md).
