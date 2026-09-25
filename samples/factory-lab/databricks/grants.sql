-- Unity Catalog grants of the lab workspace, applied before every job run.
-- All users have USE CATALOG on main by default. Tables you create are yours (you own them).

-- Analysts read the gold layer.
GRANT USE SCHEMA, SELECT ON SCHEMA main.gold TO `analysts`;

-- Data engineers build bronze to gold.
GRANT USE SCHEMA, SELECT ON SCHEMA main.source TO `data-engineers`;
GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA main.bronze TO `data-engineers`;
GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA main.silver TO `data-engineers`;
GRANT USE SCHEMA, SELECT, MODIFY, CREATE TABLE ON SCHEMA main.gold TO `data-engineers`;

-- The ML training job runs as a service principal: only what it needs.
GRANT USE SCHEMA ON SCHEMA main.source TO `sp-ml-training`;
GRANT SELECT ON TABLE main.source.turbine_readings TO `sp-ml-training`;
GRANT USE SCHEMA, CREATE MODEL ON SCHEMA main.ml TO `sp-ml-training`;
GRANT USE SCHEMA, CREATE TABLE ON SCHEMA main.gold TO `sp-ml-training`;
