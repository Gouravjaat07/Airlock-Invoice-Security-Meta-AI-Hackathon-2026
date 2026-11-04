-- Migration 3: store only SHA-256 of approval-challenge bearers.
--
-- Rationale: a challenge id authorizes by knowledge alone (presenting
-- it plus the owner PIN authorizes a mock payment). Sessions and CSRF tokens
-- already store hashes only; challenges stored the raw bearer, so any
-- database read disclosed unconsumed approvals. The new
-- `auth_challenges.challenge_hash` primary key holds
-- `sha256(challenge_id)`; the application hashes at the boundary
-- (see app/auth/challenges.py).
--
-- Data handling: SQLite cannot compute SHA-256 in SQL, so pending
-- challenges CANNOT be carried over. This is safe and fail-closed:
-- challenges are single-use with a 5-minute TTL, never business
-- records; after the upgrade the owner simply re-issues a challenge
-- (POST /api/v1/proposals/{id}/challenge). No case, proposal, payment,
-- vendor, or audit data is touched.
DROP TABLE IF EXISTS auth_challenges;
CREATE TABLE auth_challenges (
    challenge_hash TEXT PRIMARY KEY,
    proposal_hash  TEXT NOT NULL,
    session_id     TEXT NOT NULL REFERENCES auth_sessions(session_id),
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    used_at        TEXT,
    failed_attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_challenges_proposal ON auth_challenges(proposal_hash);
