# Migration du pool dédié Synapse vers Fabric Warehouse

Complétez cette check-list pour l'équipe. Une ou deux lignes par point.

## Conception physique

- Quelles tables étaient `REPLICATE`, lesquelles `HASH` et sur quelle colonne ? Que devient ce choix dans Fabric ?
- Quelles tables étaient partitionnées ? Par quoi Fabric remplace-t-il la partition et l'élimination de partitions ?

## Types et contraintes

- Quels types avez-vous dû changer (`nvarchar`, `money`, ...) et par quoi ?
- Clés primaires et étrangères : que garantissent-elles dans Synapse, et dans Fabric ?

## Chargement

- Quelle procédure stockée le pipeline appelle-t-il, avec quels paramètres typés ?
- Qu'est-ce qui changerait pour ce pipeline dans Fabric Data Factory ?

## Gouvernance

- D'où vient `margin_amount` de `gold.fct_sales` (lignage), et quel contrôle du modèle en étoile vous rassure sur son grain ?
