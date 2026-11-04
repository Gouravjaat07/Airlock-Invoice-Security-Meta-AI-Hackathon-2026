-- Migration 2: record the policy version on every proposal (spec 13.1).
-- Existing rows (prototype only) default to 2.0.0; new inserts pass it
-- explicitly from settings.
ALTER TABLE proposals ADD COLUMN policy_version TEXT NOT NULL DEFAULT '2.0.0';
