-- Projet « Retail de bout en bout » : les commandes web en silver.
-- Mosaic > Run active SQL exécute ce fichier sur le catalogue local (DuckDB).
--
-- bronze.web_orders vient de l'import CSV : toutes ses colonnes sont du texte.
-- Construisez silver.web_orders avec :
--   - order_id et customer_id en texte ;
--   - segment_id en INTEGER et net_amount en DOUBLE ;
--   - ordered_at converti en TIMESTAMP et renommé loaded_at, comme dans les commandes magasin
--     (le pipeline Fabric ajoutera ces lignes à bronze.orders par nom de colonne) ;
--   - une seule ligne par commande (la boutique renvoie parfois une ligne en double) ;
--   - seulement les montants strictement positifs (ni remboursement ni échantillon gratuit).

CREATE OR REPLACE TABLE silver.web_orders AS
SELECT order_id,
       customer_id,
       segment_id,
       net_amount,
       ordered_at
FROM bronze.web_orders;
