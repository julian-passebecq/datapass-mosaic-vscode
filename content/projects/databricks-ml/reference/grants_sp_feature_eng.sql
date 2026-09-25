-- The feature job runs as a service principal: only what it needs.
GRANT USE SCHEMA ON SCHEMA main.source TO `sp-feature-eng`;
GRANT SELECT ON TABLE main.source.turbine_readings TO `sp-feature-eng`;
GRANT USE SCHEMA, CREATE TABLE ON SCHEMA main.silver TO `sp-feature-eng`;
