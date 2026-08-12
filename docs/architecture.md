# Mitori アーキテクチャ図

## 全体構成

```mermaid
graph TB
    subgraph External APIs
        OSV[OSV API]
        EOL[endoflife.date API]
        TAXII[MITRE ATT&CK TAXII]
        KEV_API[CISA KEV Catalog]
        EPEL[EPEL Mirrorlist]
    end

    subgraph Slack
        WEBHOOK[Slack Incoming Webhook]
    end

    subgraph k3s Cluster
        subgraph app namespace
            subgraph CronJobs
                CVE[cve-watch]
                COV[cve-coverage-report]
                EOLW[eol-watch]
                LIFE[lifecycle-notify]
                INV[inventory-scan]
                MIRROR[mirror-check]
                MITC[mitre-collector]
                MITN[mitre-normalizer]
                KEVC[kev-collector]
                KEVN[kev-notify]
                CKA[cve-kev-alert]
            end

            DB[(MariaDB)]

            subgraph ConfigMaps
                COMMON[common-lib<br/>db.py / slack.py]
                SCRIPTS[各サービス-script]
            end
        end

        subgraph monitoring namespace
            PROM[Prometheus]
            GRAF[Grafana]
            LOKI[Loki]
            ALLOY[Alloy DaemonSet]
        end
    end

    %% External API → CronJob
    OSV --> CVE
    EOL --> EOLW
    TAXII --> MITC
    KEV_API --> KEVC
    EPEL --> MIRROR

    %% CronJob → DB
    CVE --> DB
    EOLW --> DB
    MITC --> DB
    MITN --> DB
    INV --> DB
    KEVC --> DB
    COV --> DB
    CKA --> DB

    %% CronJob → Slack
    CVE --> WEBHOOK
    EOLW --> WEBHOOK
    LIFE --> WEBHOOK
    MIRROR --> WEBHOOK
    INV --> WEBHOOK
    MITN --> WEBHOOK
    KEVN --> WEBHOOK
    CKA --> WEBHOOK
    COV --> WEBHOOK

    %% DB reads (normalizer reads collector data)
    DB --> MITN
    DB --> LIFE
    DB --> KEVN
    DB --> CKA
    DB --> COV

    %% ConfigMap mounts
    COMMON -.-> CVE
    COMMON -.-> EOLW
    COMMON -.-> MITC
    COMMON -.-> MITN
    COMMON -.-> INV
    COMMON -.-> KEVC
    COMMON -.-> KEVN
    COMMON -.-> CKA
    COMMON -.-> COV
    COMMON -.-> LIFE

    %% Monitoring
    ALLOY --> LOKI
    PROM --> GRAF
    LOKI --> GRAF
```

## データフロー（CronJob 実行サイクル）

```mermaid
flowchart LR
    A[外部API] -->|定期取得| B[CronJob]
    B -->|書き込み| C[(MariaDB)]
    C -->|前回データ読み出し| B
    B -->|差分検知時| D[Slack通知]

    style A fill:#e1f5fe
    style C fill:#fff3e0
    style D fill:#e8f5e9
```

## サービス依存関係

```mermaid
graph LR
    subgraph 収集系
        MITC[mitre-collector]
        KEVC[kev-collector]
        EOLW[eol-watch]
        INV[inventory-scan]
        CVE[cve-watch]
    end

    subgraph 分析・通知系
        MITN[mitre-normalizer]
        KEVN[kev-notify]
        CKA[cve-kev-alert]
        COV[cve-coverage-report]
        LIFE[lifecycle-notify]
    end

    MITC -->|raw data| MITN
    KEVC -->|KEV entries| KEVN
    KEVC -->|KEV entries| CKA
    CVE -->|CVE entries| CKA
    INV -->|inventory| CVE
    INV -->|inventory| COV
    EOLW -->|EOL dates| LIFE
```
