-- Migration 026: Full-Text Search Index for Hybrid Retrieval
-- Week 27: Advanced RAG Pipeline
-- Date: April 30, 2026
--
-- Adds a tsvector column + GIN index to enriched_anomalies for fast
-- PostgreSQL full-text search.  Weighted: A = user identity, B = root cause
-- classification, C = severity/status, D = reasoning text.
--
-- Also indexes the llm_explanations text columns for cross-table FTS.

BEGIN;

-- 1. Add tsvector column to enriched_anomalies
ALTER TABLE enriched_anomalies
    ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- 2. Populate search_vector for existing rows
UPDATE enriched_anomalies SET search_vector =
    setweight(to_tsvector('english', COALESCE(user_id, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(root_cause, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(sub_category, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(classification_reasoning, '')), 'C') ||
    setweight(to_tsvector('english', COALESCE(validation_reasoning, '')), 'C') ||
    setweight(to_tsvector('english', COALESCE(severity, '')), 'D') ||
    setweight(to_tsvector('english', COALESCE(status, '')), 'D');

-- 3. GIN index for fast FTS queries
CREATE INDEX IF NOT EXISTS idx_enriched_anomalies_fts
    ON enriched_anomalies USING GIN (search_vector);

-- 4. Trigger to keep search_vector up-to-date on INSERT/UPDATE
CREATE OR REPLACE FUNCTION enriched_anomalies_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.user_id, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.root_cause, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.sub_category, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.classification_reasoning, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.validation_reasoning, '')), 'C') ||
        setweight(to_tsvector('english', COALESCE(NEW.severity, '')), 'D') ||
        setweight(to_tsvector('english', COALESCE(NEW.status, '')), 'D');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_enriched_anomalies_search_vector ON enriched_anomalies;
CREATE TRIGGER trigger_enriched_anomalies_search_vector
    BEFORE INSERT OR UPDATE OF user_id, root_cause, sub_category,
        classification_reasoning, validation_reasoning, severity, status
    ON enriched_anomalies
    FOR EACH ROW
    EXECUTE FUNCTION enriched_anomalies_search_vector_update();

-- 5. Add tsvector column to llm_explanations for cross-table FTS
ALTER TABLE llm_explanations
    ADD COLUMN IF NOT EXISTS search_vector tsvector;

UPDATE llm_explanations SET search_vector =
    setweight(to_tsvector('english', COALESCE(context_analysis, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(pattern_analysis, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(risk_assessment, '')), 'C');

CREATE INDEX IF NOT EXISTS idx_llm_explanations_fts
    ON llm_explanations USING GIN (search_vector);

CREATE OR REPLACE FUNCTION llm_explanations_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.context_analysis, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.pattern_analysis, '')), 'B') ||
        setweight(to_tsvector('english', COALESCE(NEW.risk_assessment, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_llm_explanations_search_vector ON llm_explanations;
CREATE TRIGGER trigger_llm_explanations_search_vector
    BEFORE INSERT OR UPDATE OF context_analysis, pattern_analysis, risk_assessment
    ON llm_explanations
    FOR EACH ROW
    EXECUTE FUNCTION llm_explanations_search_vector_update();

COMMIT;
