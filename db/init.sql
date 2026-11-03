-- run by postgres only on first start, when the data volume is empty
CREATE TABLE IF NOT EXISTS monitors (
    id         BIGSERIAL PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    url        TEXT NOT NULL,
    interval_s INT NOT NULL DEFAULT 30 CHECK (interval_s BETWEEN 10 AND 3600),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS checks (
    id          BIGSERIAL PRIMARY KEY,
    monitor_id  BIGINT NOT NULL REFERENCES monitors(id) ON DELETE CASCADE,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    up          BOOLEAN NOT NULL,
    status_code INT,
    latency_ms  INT,
    error       TEXT
);

CREATE INDEX IF NOT EXISTS idx_checks_monitor_time ON checks (monitor_id, checked_at DESC);
