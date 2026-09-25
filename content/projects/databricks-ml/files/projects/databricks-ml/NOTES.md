# Revue du lakehouse éolien

Notez vos réponses en quelques lignes. Les chiffres de calcul et de coût du labo sont illustratifs (DBU de
labo) : comparez-les entre eux, pas avec une facture Azure.

## Calcul et coût

- Quel calcul (job cluster, cluster partagé, serverless, SQL warehouse) chaque job utilise-t-il ?
- Combien de DBU de labo coûte un run de `turbine_features`, et combien de plus quand la première tentative échoue ?

## Unity Catalog

- Quels droits minimaux `sp-feature-eng` a-t-il reçus, et pourquoi pas `ALL PRIVILEGES` sur le catalogue ?
- Qui possède `main.silver.turbine_features` et `main.ml.power_model` ?

## MLflow

- Quelle version du modèle porte l'alias `champion`, et pourquoi le scoring n'a-t-il pas besoin de changer de code ?
