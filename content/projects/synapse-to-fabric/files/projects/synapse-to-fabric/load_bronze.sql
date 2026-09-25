-- Projet « Entrepôt Synapse vers Fabric Warehouse » : charger le bronze.
-- Mosaic > Run active SQL exécute ce fichier sur le catalogue local (DuckDB).
--
-- Le pipeline Synapse pl_sqlpool_daily part de bronze.orders. Dans le service, une activité Copy ou un
-- COPY INTO l'alimenterait depuis le data lake ; ici, on recopie la source brute telle quelle.
CREATE OR REPLACE TABLE bronze.orders AS
SELECT order_id, customer_id, segment_id, net_amount, loaded_at
FROM source.orders;

SELECT COUNT(*) AS orders, SUM(net_amount) AS net_amount FROM bronze.orders;
