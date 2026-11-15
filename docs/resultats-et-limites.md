# Résultats de l’instantané avant publication — 15 novembre 2026

> Document historique : pour le système désormais destiné à GitHub et sa planification, voir [publication-github.md](publication-github.md).

**54 chaînes réellement relues avec image et son depuis le PC Sunrise en Suisse. Guide vérifié pour 45 chaînes. RTS 1 et RTS 2 sont présentes et ont aussi été décodées pendant quinze secondes en Full HD avec audio français.**

## Correction de la première conclusion

La première livraison de 17 chaînes avait écarté trop tôt les liens net+ des dépôts GitHub. Ils n’avaient pas été testés sur Sunrise. Les DRM du lecteur SRG et les échecs multicast ne permettaient pas de conclure à l’absence d’une autre distribution utilisable. Les URL d’entrée net+ fonctionnent sur ce PC sans compte ni achat ; elles sont maintenant prises en compte dans la sélection domestique.

Un second défaut a été reproduit dans le vérificateur : il choisissait systématiquement la variante HLS au débit le plus faible. Le manifeste RTS 2 contient aussi des variantes uniquement audio ; le contrôle échouait alors faute de vidéo. Le choix préfère maintenant les variantes vidéo reconnues avant de minimiser leur débit, puis sélectionne le groupe audio français. Ce cas est documenté par le manifeste archivé et couvert par un test avec véritable décodage HLS. Les [exemples de la spécification HLS](https://www.rfc-editor.org/rfc/rfc8216#section-8.6) montrent ces variantes audio seules.

Un nom de domaine de distributeur ne prouve pas une restriction au réseau de ce distributeur. Une revue explicite peut retenir une entrée HTTP sur Internet après lecture CH avec un autre FAI identifié. La correspondance opérateur reste obligatoire pour le multicast.

## Sélection disponible

Le catalogue contient 520 identités candidates et 909 sources dédupliquées par identité et URL exacte, y compris des variantes historiques ou non résolues. Ce vivier n’est pas une liste de chaînes toutes validées. Le M3U final contient 54 identités distinctes, dans l’ordre du profil Suisse romande : RTS 1, RTS 2, TF1 Suisse, France 2–5, M6 Suisse et ARTE en tête.

Le fichier à utiliser est **`output/domestic/swiss-fr-internet.m3u`**, également fourni dans `output/domestic/Swiss_IPTV_FR_Kodi.zip`. La sélection complète `swiss-fr.m3u` contient actuellement les mêmes chaînes. Les [instructions Kodi](kodi-sunrise.md) restent disponibles pour le chargement ; les vérifications média ont été effectuées sur le PC.

| Sélection | Chaînes | Guide vérifié |
|---|---:|---:|
| `swiss-fr.m3u` | 54 | 45 |
| `swiss-fr-internet.m3u` | 54 | 45 |
| `swiss-fr-multicast.m3u` | 0 | 0 |
| `swiss-fr-regional.m3u` | 10 | 8 |
| `swiss-fr-news.m3u` | 10 | 7 |

## Lectures et provenance

La mise à jour complète s’est terminée à `2026-11-15T11:38:48.685111+00:00`. Les 54 URL approuvées ont toutes passé leur dernier contrôle image et son, avec pays CH et FAI déclaré Sunrise. Le pays est aussi appuyé par l’observation Cloudflare archivée, sans conservation de l’adresse IP. Le contrôle ordinaire décode environ cinq secondes ; les deux RTS ont bénéficié du contrôle Full HD complémentaire.

| Chaîne | Provenance retenue | Dimensions de l’échantillon ordinaire | Guide futur |
|---|---|---:|---|
| RTS 1 | distributeur net+ | 768 × 432 | oui |
| RTS 2 | distributeur net+ | 768 × 432 | oui |
| TF1 Suisse | distributeur net+ | 768 × 432 | oui |
| France 2 | distributeur net+ | 768 × 432 | oui |
| France 3 | distributeur net+ | 768 × 432 | oui |
| France 4 | distributeur net+ | 768 × 432 | oui |
| France 5 | distributeur net+ | 768 × 432 | oui |
| M6 Suisse | distributeur net+ | 768 × 432 | oui |
| arte | distributeur net+ | 768 × 432 | oui |
| W9 Suisse | distributeur net+ | 768 × 432 | oui |
| TMC | distributeur net+ | 768 × 432 | oui |
| TFX Suisse | distributeur net+ | 768 × 432 | oui |
| 6ter Suisse | distributeur net+ | 768 × 432 | oui |
| TV5MONDE FBS | diffuseur / lecteur relié | 384 × 216 | oui |
| KTO | diffuseur / lecteur relié | 320 × 180 | oui |
| TV Monaco | distributeur net+ | 768 × 432 | oui |
| T18 | distributeur net+ | 768 × 432 | non validé |
| NOVO19 | distributeur net+ | 768 × 432 | non validé |
| TF1 Series Films | distributeur net+ | 768 × 432 | oui |
| RMC Life | distributeur net+ | 768 × 432 | non validé |
| AB3 | distributeur net+ | 768 × 432 | non validé |
| RMC Decouverte | distributeur net+ | 768 × 432 | oui |
| RMC Story | distributeur net+ | 768 × 432 | oui |
| RTS Info | diffuseur / lecteur relié | 480 × 270 | non validé |
| Franceinfo | distributeur net+ | 768 × 432 | oui |
| BFM TV | distributeur net+ | 768 × 432 | oui |
| BFM Business | distributeur net+ | 768 × 432 | non validé |
| CNews | distributeur net+ | 768 × 432 | oui |
| LCI | distributeur net+ | 768 × 432 | oui |
| LCP | distributeur net+ | 768 × 432 | oui |
| Euronews French | distributeur net+ | 768 × 432 | oui |
| France 24 | diffuseur / lecteur relié | 640 × 360 | oui |
| TV5MONDE Info | diffuseur / lecteur relié | 384 × 216 | non validé |
| Léman Bleu | diffuseur / lecteur relié | 640 × 360 | oui |
| TV8 Mont-Blanc | distributeur net+ | 768 × 432 | oui |
| Canal 9 | diffuseur / lecteur relié | 1920 × 1080 | oui |
| Canal Alpha Jura | diffuseur / lecteur relié | 640 × 360 | oui |
| Canal Alpha Neuchâtel | diffuseur / lecteur relié | 640 × 360 | oui |
| La Télé | diffuseur / lecteur relié | 640 × 360 | oui |
| TeleBielingue | distributeur net+ | 768 × 432 | oui |
| Canal B français | distributeur net+ | 768 × 432 | non validé |
| MaxTV / DieuTV | distributeur net+ | 768 × 432 | oui |
| NRTV | distributeur net+ | 768 × 432 | oui |
| Val TV | distributeur net+ | 768 × 432 | non validé |
| Carac 1 | diffuseur / lecteur relié | 640 × 360 | oui |
| Carac 2 | diffuseur / lecteur relié | 640 × 360 | oui |
| Carac 3 | diffuseur / lecteur relié | 640 × 360 | oui |
| Carac 4 | diffuseur / lecteur relié | 640 × 360 | oui |
| Carac 5 | diffuseur / lecteur relié | 640 × 360 | oui |
| Rhône TV | diffuseur / lecteur relié | 1920 × 1080 | oui |
| TVM3 | diffuseur / lecteur relié | 1920 × 1080 | oui |
| Blue Zoom F | distributeur net+ | 768 × 432 | oui |
| L'Équipe | distributeur net+ | 768 × 432 | oui |
| Gulli | distributeur net+ | 768 × 432 | oui |

Les dimensions ordinaires proviennent généralement de la variante vidéo à faible débit. Elles ne sont pas nécessairement le maximum disponible : le M3U garde le manifeste maître. **RTS 1 et RTS 2 ont chacune décodé 750 images en quinze secondes, 1920 × 1080, H.264 et AAC, avec sélection de l’audio français**, lors du contrôle complémentaire. Les détails et images de preuve sont dans `data/evidence/netplus/fullhd-and-identity.json`. Des images ont également été examinées pour MaxTV / DieuTV, Val TV et AB3. Ce contrôle ponctuel ne certifie pas chaque émission future.

Les 37 sources net+ ajoutées restent identifiées comme provenant du distributeur. Leur présence dans [la liste GitHub examinée](https://github.com/iptv-ch/iptv-ch.github.io/blob/master/netplus.m3u8), les réponses des serveurs net+ et les empreintes des manifestes constituent la chaîne de provenance technique. L’instantané et les documents de revue sont dans `data/evidence/netplus/provenance.json` et `domestic-selection-review.json`. Les sources directes des diffuseurs gardent la priorité lorsqu’elles sont validées.

Les entrées net+ peuvent rediriger normalement vers des sessions CDN temporaires liées à la connexion. Ces sessions ne sont ni fabriquées, ni modifiées, ni copiées dans le M3U ; leurs chemins sont masqués dans les journaux. Chaque lecteur contacte l’entrée publique stable et obtient sa propre redirection. Aucune clé, licence DRM, connexion à un compte ou modification de restriction géographique n’a été utilisée.

## Guide XMLTV

Le [guide CH1 d’EPGSHARE01](https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz) a été téléchargé et analysé de nouveau pendant la mise à jour. Les 45 correspondances EPG présentes dans le M3U ont des programmes futurs au moment du contrôle. L’en-tête contient `url-tvg` et `x-tvg-url` et les identifiants correspondent au XMLTV effectivement analysé.

Correspondances non validées : **T18, NOVO19, RMC Life, AB3, RTS Info, BFM Business, TV5MONDE Info, Canal B français, Val TV**. Aucun guide n’est inventé pour ces chaînes. La présence de programmes ne garantit pas leur exactitude éditoriale.

Le [fournisseur](https://epgshare01.online/) annonce un guide gratuit pour usage légal. Seul son lien est inclus pour le foyer ; la grille n’est pas réhébergée. Les documents de provenance sont archivés dans `data/evidence/epg-provider.json`. XMLTV.ch retourne encore HTTP 503 et XMLTV.fr échoue au contrôle TLS ; ces replis ne sont pas annoncés comme fonctionnels. Le projet dépend donc encore d’un tiers pour l’EPG.

## Revue domestique et limites

Les 54 décisions exactes restent limitées à la lecture personnelle du foyer suisse, selon le [cadre de l’IPI](https://www.ige.ch/fr/proteger-votre-pi/droit-dauteur/utiliser-une-oeuvre/droit-dauteur-et-internet). Les [CG net+](https://www.netplus.ch/media/document/0/conditions-generales-net.pdf) et [l’offre TV Mobile](https://www.netplus.ch/fr/app-tv-mobile-547) ont été examinées et archivées. La lecture constatée sans compte ne vaut ni abonnement ni permission générale du distributeur. L’offre commerciale TV Mobile n’est pas présentée comme gratuite. Les bouquets premium ne sont pas ajoutés ; aucune autorisation de publier ou de rediffuser programmes, liens ou logos n’est déduite de cette revue.

Les exports publics restent vides, et aucun déploiement Pages n’a été effectué. TV5MONDE Europe, ORTB/Bénin TV et d’autres télévisions locales restent non validées ou à examiner. Les essais multicast Sunrise restent infructueux sans cause déterminée ; ils ne sont pas nécessaires pour recevoir les deux RTS via les entrées Internet retenues. Les refus et DRM constatés dans les lecteurs directs SRG/ARTE restent attachés à ces lecteurs précis.

La disponibilité continue, tous les horaires et les autres FAI ne sont pas garantis par ces échantillons. Le comportement de l’interface Kodi sur le Raspberry Pi n’a pas été observé à distance. Une entrée du distributeur peut changer ou être retirée : la mise à jour teste directement les URL approuvées et conserve l’historique, sans attendre une correction de la liste GitHub d’origine. Une URL nouvelle doit recevoir sa propre revue. Les revues expirent après 90 jours, les lectures après 48 heures et le guide après 24 heures.

## Vérifications de livraison

35 tests automatisés ont réussi sous Windows, dont les vrais décodages HLS/DASH synthétiques, le cas HLS vidéo + audio seule à moindre débit, l’audio français séparé, les variantes suisses, le refus des DRM et la distinction entre exports privés et publics. Les fixtures ne prouvent pas la disponibilité des diffuseurs : les 54 lectures séparées enregistrées par source l’établissent pour ce contexte daté. Le paquet Python a aussi été reconstruit.

L’intégrité SQLite, les clés étrangères, les 54 preuves actuelles image et son, les 45 correspondances XMLTV, l’ordre des neuf premières chaînes et l’intégrité du ZIP ont été contrôlés. Le ZIP contient seulement les cinq M3U et les instructions. Les URL temporaires du CDN sont absentes des playlists. Les résultats structurés sont dans `output/audit/livraison.json`, `selection.json`, `selection.csv` et `checks.json`.

Le lanceur local de mise à jour fonctionne à la demande ; aucune nouvelle approbation n’est créée automatiquement. Aucune tâche quotidienne Windows ou publication distante n’est activée. Linux, les workflows GitHub, la collecte autonome EPG et l’automatisation générale restent à mettre en service après cette première phase.
