-- mitre-sync mini 用テーブル初期化

CREATE TABLE IF NOT EXISTS mitre_raw_staging (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(20) NOT NULL,
    fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_json LONGTEXT NOT NULL,
    processed_at DATETIME NULL,
    INDEX idx_unprocessed (source, processed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mitre_taxii_cursor (
    collection_id VARCHAR(100) NOT NULL PRIMARY KEY,
    next_offset INT NOT NULL DEFAULT 0,
    last_added_after DATETIME NULL,
    page_size INT NOT NULL DEFAULT 500,
    total_count INT NULL,
    next_run_at DATETIME NULL,
    backoff_minutes INT NOT NULL DEFAULT 60,
    last_fetch_count INT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mitre_tactics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,
    tactic_key VARCHAR(50) NOT NULL UNIQUE,
    external_id VARCHAR(20) NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mitre_techniques (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stix_id VARCHAR(100) NOT NULL UNIQUE,
    external_id VARCHAR(20) NOT NULL UNIQUE,
    parent_external_id VARCHAR(20) NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_subtechnique BOOLEAN NOT NULL DEFAULT FALSE,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    content_hash CHAR(64) NOT NULL,
    stix_modified DATETIME NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_parent (parent_external_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS mitre_technique_tactic_map (
    technique_id INT NOT NULL,
    tactic_id INT NOT NULL,
    PRIMARY KEY (technique_id, tactic_id),
    FOREIGN KEY (technique_id) REFERENCES mitre_techniques(id) ON DELETE CASCADE,
    FOREIGN KEY (tactic_id) REFERENCES mitre_tactics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
