-- eol-watch mini 用テーブル初期化

CREATE TABLE IF NOT EXISTS monitor_targets (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_slug VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200) NOT NULL,
    status ENUM('pending_validation','active','error','invalid') NOT NULL DEFAULT 'pending_validation',
    consecutive_failures INT NOT NULL DEFAULT 0,
    last_checked_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS eol_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id INT NOT NULL,
    raw_json LONGTEXT NOT NULL,
    collected_at DATETIME NOT NULL,
    FOREIGN KEY (target_id) REFERENCES monitor_targets(id) ON DELETE CASCADE,
    INDEX idx_target_collected (target_id, collected_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 監視対象
INSERT INTO monitor_targets (product_slug, display_name) VALUES
    ('python', 'Python'),
    ('mariadb', 'MariaDB'),
    ('k3s', 'k3s'),
    ('almalinux', 'AlmaLinux');
