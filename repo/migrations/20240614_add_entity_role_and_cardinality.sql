-- Migration: add entity roles and relationship cardinalities
-- Applies to SQLite (development default). For other RDBMS adjust syntax as required.

ALTER TABLE entities
    ADD COLUMN entity_role TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE relationships
    ADD COLUMN cardinality_from TEXT NOT NULL DEFAULT 'unknown';

ALTER TABLE relationships
    ADD COLUMN cardinality_to TEXT NOT NULL DEFAULT 'unknown';
