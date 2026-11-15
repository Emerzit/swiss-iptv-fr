# Audit initial — 15 novembre 2026

Ce document conserve **l’état historique de l’import et des premiers essais**, avant l’extension de la sélection. Pour l’état courant (54 chaînes avec image et son, guide pour 45 chaînes, RTS 1/2 en Full HD via net+, essais multicast sur le PC Sunrise), lire [résultats et limites](resultats-et-limites.md) et [instructions Kodi](kodi-sunrise.md). Les chiffres et contrôles ci-dessous décrivent cet instantané initial. L’utilisateur a ensuite précisé que tous les tests doivent être réalisés sur le PC ; le Raspberry Pi sert uniquement de lecteur Kodi. Aucun lien n’a été déployé sur GitHub Pages.

## Inventaire obtenu

Le catalogue contient **519 identités candidates et 886 sources dédupliquées**, dont 31 identités suisses, 172 françaises et 24 belges. Le reste couvre notamment la francophonie internationale et des services FAST dont la langue est française, même si le pays d'origine est différent. Ces nombres décrivent un vivier à examiner, pas une offre gratuite certifiée.

| Protocole détecté par l'URL | Sources candidates |
|---|---:|
| HLS | 601 |
| DASH | 56 |
| RTP multicast | 216 |
| UDP multicast | 3 |
| HTTP non identifié | 10 |

L'import a traité 1 353 occurrences retenues. Il a filtré 45 occurrences d'offres payantes connues, 40 URL signées ou contenant des paramètres d'authentification et 65 relais opérateur non examinés. Ces filtres sont initiaux et non exhaustifs : toute autre source conserve le statut de droits `pending`. Les URL identiques d'une même chaîne sont rapprochées, leurs origines multiples restent conservées. **27 identités `local.*`** attendent un rapprochement éditorial ; elles ne sont pas fusionnées sur une ressemblance incertaine.

Livrables locaux : `data/catalog.sqlite`, `output/audit/candidates.csv`, `channels.json`, `sources.json`, `origins.json`, `checks.json`, `summary.json` et `verification.md`. Les fichiers détaillés contiennent des liens non approuvés : ils sont ignorés par Git et ne font pas partie du dossier Pages. Les métadonnées publiques et les documents de provenance sont datés et hachés dans `data/upstream/manifest.json` ; les preuves des pages officielles sont dans `data/evidence/`.

## Lecture réellement observée

La connexion de test Windows est signalée **CH** par le point de diagnostic Cloudflare. L'observation et son empreinte sont dans `data/egress-context.json` ; l'adresse IP n'est pas conservée. Les premières lectures ont été enregistrées avec pays inconnu, puis les dix sources réussies ont été relues avec le contexte CH. Cela prouve un échantillon accessible depuis cette connexion, pas depuis tous les opérateurs suisses ni pendant tous les programmes.

| Chaîne | Vidéo décodée | Résolution observée | Résultat |
|---|---:|---:|---|
| France 24 français | 5 s | 640 × 360 | H.264, lecture réussie |
| Léman Bleu | 5 s | 640 × 360 | H.264, lecture réussie |
| La Télé | 5 s | 640 × 360 | H.264, deux URL dont celle retrouvée sur le site officiel |
| Canal Alpha Jura | 5 s | 640 × 360 | H.264, lecture réussie |
| Canal Alpha Neuchâtel | 5 s | 640 × 360 | H.264, lecture réussie |
| Canal 9 | 5 s | 1920 × 1080 | H.264, lecture réussie |
| RTS Info | 5 s | 480 × 270 | H.264, groupe audio séparé non vérifié |
| TV5MONDE Info | environ 5 s | 384 × 216 | H.264, groupe audio séparé non vérifié |
| BX1 | 5 s | 1280 × 720 | H.264, lecture réussie |

Ce sont **neuf chaînes et dix URL lues**, et non 519 chaînes validées. Le vérificateur choisit une variante à faible débit : la résolution observée n'est pas nécessairement le maximum disponible. Les codecs audio AAC ont été identifiés quand présents dans la variante vidéo ; l'audio lui-même n'a pas été décodé. Le contrôle de l'identité visuelle des programmes et la lecture audio complète restent à effectuer.

Une source multicast RTS 1 a été soumise au garde-fou : résultat `network_required`, sans ouverture de flux. Aucun multicast n'est déclaré fonctionnel. Le prototype DASH a été validé par une vraie lecture d'un MPD et de segments H.264 synthétiques locaux ; aucun diffuseur DASH n'est déclaré vérifié sur cette base.

Les quatorze tests automatisés couvrent notamment le parsing M3U, l'idempotence, les langues des feeds, l'exclusion des replays et URL signées, les critères de publication, le périmètre privé/public, l'expiration des preuves, le refus du chiffrement, les tentatives répétées, la distinction d'un 403 et les lectures réelles HLS/DASH avec un cas de segments manquants. Ils ont réussi sous Windows. Les workflows Windows/Linux sont préparés mais n'ont pas encore été exécutés sur GitHub.

## Audit des quatre projets de référence

Les fichiers GitHub sont figés sur les révisions suivantes. Les API et la playlist générée en français sont des instantanés horodatés, avec empreintes, sans garantie de cohérence transactionnelle entre deux projets amont.

| Projet | Révision examinée |
|---|---|
| iptv-ch/iptv-ch.github.io | `a1e970d8092bad06f65dcbbed7678bd97745cef1` |
| iptv-org/iptv | `568ba9b9d6f1d476e0ecf206d83e71c171568d81` |
| iptv-org/database | `d7886b4544ec23078e0d246b17b1bcf6cc421aff` |
| iptv-org/epg | `6530f23d31a12fca3352f8a1398a67bc8ccca5e6` |

**iptv-ch.** Le dépôt regroupe des listes par opérateur et langue, mêlant HTTP, HLS, DASH et RTP/UDP. Des fichiers portant l'extension `.mpd` sont en réalité des collections M3U de liens vers des MPD : l'extension ne suffit pas à identifier le contenu. Le README distingue notamment les contraintes réseau Swisscom et Init7. Les mises à jour sont visibles dans l'historique, mais aucun workflow de validation automatisée ni licence explicite n'a été trouvé dans l'arbre examiné. Son avertissement d'usage privé est une déclaration du mainteneur, pas une autorisation de chaque diffuseur. Des métadonnées historiques et lignes malformées exigent des contrôles à l'import. [Dépôt et documentation](https://github.com/iptv-ch/iptv-ch.github.io).

**iptv-org/iptv.** Les fichiers internes sont des collections M3U par pays. Le workflow quotidien met à jour les entrées issues des contributions, vérifie la structure et génère les listes publiques et données API. Les identifiants peuvent inclure un suffixe de feed `@...`, à conserver pour l'EPG et pour éviter de confondre les langues. La présence d'un lien dans cette collection constitue une piste de découverte ; elle ne suffit pas à approuver son accès en Suisse. [Code et workflows](https://github.com/iptv-org/iptv).

Le test technique examiné télécharge une réponse et l'analyse avec MediaInfo.js. Il ne démontre pas à lui seul le décodage temporel de segments par FFmpeg. Swiss IPTV FR conserve donc son propre critère de lecture réelle. [Implémentation du test](https://github.com/iptv-org/iptv/blob/master/scripts/core/streamTester.ts).

**iptv-org/database.** Les données éditables sont des CSV, publiées aussi sous forme d'API JSON. Les chaînes, feeds et logos sont distincts ; dans l'instantané actuel, les langues sont portées par les feeds. Le workflow applique les contributions et valide les données. Cette base est utile pour les identifiants, noms et catégories, mais ne certifie pas les droits des programmes. Une anomalie observée associe les deux feeds Canal Alpha romands à `deu` : une correction locale explicite, documentée par le diffuseur, les conserve comme candidats francophones. Les variantes JU/NE historiques sont rapprochées explicitement, pas par comparaison approximative. [Base et guide de contribution](https://github.com/iptv-org/database).

**iptv-org/epg.** Le projet fournit des outils de collecte par site et des correspondances de chaînes vers XMLTV. Il permet de régler les délais et le parallélisme ; son exécution implique les conditions des fournisseurs de programmes. Il sert ici de référence pour les identifiants et pour l'architecture future, sans collecte ni republication de guides dans cette phase. La licence des scripts et données du dépôt ne doit pas être interprétée comme une licence des grilles aspirées ou des programmes télévisés. [Documentation EPG](https://github.com/iptv-org/epg).

Les fichiers `LICENSE` des trois projets iptv-org ont été archivés ; les mentions du README et des métadonnées de paquet ne sont pas toujours formulées de façon identique. Aucun code amont n'a été copié dans le prototype. La licence MIT locale concerne le code original, pas les flux, marques ou logos.

## Provenance officielle et restrictions

La recherche a examiné 25 pages de diffuseurs suisses, français, belges et internationaux. L'extraction générique est volontairement limitée ; plusieurs lecteurs dépendent de configurations JavaScript, services dynamiques ou accès soumis à conditions. Un 403 de page web ne démontre pas que le flux est en panne. Les erreurs HTTP, TLS et les pages déplacées sont conservées dans `data/evidence/discovery.json`.

Le module public du lecteur **La Télé** référence son HLS avec un paramètre DVR non secret. La chaîne de provenance page → module → composant et leurs empreintes est archivée dans `data/evidence/latele-module/discovery.json`. Un seul lien est ainsi marqué officiel par extraction dans cette phase, sans approbation de droits. [Direct officiel](https://latele.ch/live).

| Famille de candidats | Accès et réserve de revue |
|---|---|
| RTS 1 / RTS 2 / RTS Info | Partir de Play RTS ; distinguer les droits par programme, le direct national et l'info. Ne pas assimiler Play RTS à Play Suisse. Conditions d'usage privé à lire à la source ; aucune permission publique déduite d'une copie tierce inaccessible directement. |
| Léman Bleu, La Télé, Canal 9, Canal Alpha, TéléBielingue | Directs régionaux proposés sur leurs sites ; vérifier le lien exact, la variante linguistique et les droits de publication du lien/logo. Une page peut aussi contenir des replays. |
| France 24 / TV5MONDE | Distinguer versions françaises, autres langues et zones de diffusion. La lecture observée ne vaut pas autorisation de republication d'une URL ou d'un logo. |
| France Télévisions / TF1 / ARTE | Les pages officielles constituent des candidats ; ne pas remplacer leurs contrôles d'accès par une URL de distributeur trouvée ailleurs. Droits territoriaux et conditions du lecteur à vérifier. |
| RTBF / chaînes belges | Séparer les chaînes Auvio et les régionales. Une lecture BX1 n'établit pas l'accès à La Une ou Tipik. |
| Swisscom / Init7 / Citycable / Netplus | Identifier le distributeur même pour un lien HTTP. Ne pas classer automatiquement un HLS opérateur comme Internet indépendant. Pas de validation multicast hors réseau compatible. |

Canal Alpha documente la réception en Suisse et son streaming sur son propre site ; cela confirme son intérêt dans le catalogue régional, sans autorisation implicite de redistribution. [Informations du diffuseur](https://www.canalalpha.ch/chaine/). Léman Bleu présente également son direct web. [Présentation officielle](https://www.lemanbleu.ch/fr/Services/a-propos/A-propos.html).

La RTBF précise que certains contenus sont limités à la Belgique et que la portabilité européenne est soumise à des conditions de résidence et de séjour dans l'UE ; cette exception ne permet pas de conclure à un accès général en Suisse. [Assistance officielle RTBF](https://support.rtbf.be/hc/fr-fr/articles/15710758810513-Probl%C3%A8mes-de-lecture-avec-le-replay-ou-le-direct).

Init7 indique qu'un abonnement Internet actif est nécessaire et distingue les offres compatibles multicast des offres unicast/HLS. Sa documentation exige notamment une configuration IGMP adaptée pour le multicast. [Conditions TV7](https://www.init7.net/fr/support/faq/tv7-voraussetzungen). Ces conditions sont compatibles avec un vérificateur local dédié, pas avec un test multicast GitHub Actions.

France Télévisions indique appliquer une localisation pour respecter les droits de diffusion. Le comportement doit donc être mesuré par programme et territoire plutôt que déduit de l'existence d'une chaîne dans une offre TV suisse. [Politique du groupe](https://www.francetelevisions.fr/groupe/confidentialite/politique-de-confidentialite/politique-de-confidentialite-de-france-televisions-6503).

La Télé impose une revue de l'utilisation de ses logos : l'URL de logo dans une base tierce ne remplace pas cette condition. [Espace professionnel](https://latele.ch/pro). La publication d'une liste de liens est distincte d'une rediffusion de vidéo ; les deux sujets restent séparés dans les décisions. Aucune conclusion juridique globale n'est tirée de la seule accessibilité d'une URL.

Les CGU de France Médias Monde ont aussi été récupérées directement et archivées avec le SHA-256 `fcc2d237ae452484b7d49a08d502d923f80eba039461803cca09868107b877c9`. Elles encadrent l'usage privé, les marques/logos et les liens profonds ; elles ne permettent pas d'approuver automatiquement une republication de l'URL HLS dans le présent projet. La revue de cette source est donc explicitement `pending`, avec sa preuve enregistrée. [CGU officielles](https://www.francemm.com/fr/legal-notice).

## Décision au stade initial (historique)

L'architecture et les résultats sont désormais examinables avant l'automatisation générale. Les priorités suivantes sont : revue des liens et logos des neuf chaînes lues ; contrôle de leur audio et identité ; essai sur Raspberry Pi ; validation multicast sur l'abonnement concerné ; adaptation des sources officielles restantes ; puis planification quotidienne et publication contrôlée.

Les cinq M3U sont générés sous `output/public/`, avec un rapport d'exclusion `rights_pending`. Leur contenu vide rend explicite l'absence actuelle d'autorisation éditoriale ; il ne s'agit pas d'une playlist prête à regarder. Les résultats techniques et le catalogue restent utilisables pour mener les revues sans refaire l'audit.
