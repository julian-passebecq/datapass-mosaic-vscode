# Runbook : chargement retail quotidien

Complétez ce runbook pour l'équipe d'astreinte. Répondez en quelques lignes par question.

## Ordonnancement

- À quelle heure le DAG `retail_daily_load` démarre-t-il, et que fait-il si le fichier web n'arrive pas ?
- Combien de fois le déclenchement du pipeline Fabric est-il retenté, et avec quel délai ?

## Pipeline Fabric `pl_retail_daily`

- Quelle activité échoue si `silver.orders` est vide, et qui est prévenu quand le notebook échoue ?
- Relancer le pipeline le même jour est-il sans risque ? Pourquoi (ou pourquoi pas) ?

## Qualité

- Quels contrôles protègent `silver.web_orders` (Pipeline Lab) et que se passe-t-il s'ils trouvent des lignes ?

## Entrepôt

- Comment retrouver la ville d'un client au moment d'une vente passée (SCD de type 2) ?
