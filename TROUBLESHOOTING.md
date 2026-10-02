# トラブルシューティング記録

過去に発生した問題と解決策の記録です。同じ問題に再度ハマらないための参照用。

---

## [MITRE] PyPIパッケージ名の罠

**現象**: `import taxii2client` は通るのに `pip install taxii2client` でパッケージが見つからない。

**原因**: importのモジュール名は `taxii2client`(ハイフンなし)だが、PyPIのパッケージ名は `taxii2-client`(ハイフンあり)。

**解決**: `pip install taxii2-client`

---

## [MITRE] 旧TAXIIエンドポイントへの接続タイムアウト

**現象**: `cti-taxii.mitre.org` へのリクエストがタイムアウトする。

**原因**: 旧エンドポイントは廃止済み。

**解決**: `https://attack-taxii.mitre.org/api/v21/` を使う。

---

## [MITRE] `taxii2client.v21.Server` に API Root URL を渡すと `api_roots` が空

**現象**: `Server(API_ROOT_URL).api_roots` が空リストで返る。

**原因**: `Server` クラスは Discovery URL(ルートエンドポイント)を受け取る想定。API Root URL を直接渡しても正しく解釈されない。

**解決**: API Root URL には `ApiRoot` クラスを直接使う。

```python
from taxii2client.v21 import ApiRoot

api_root = ApiRoot("https://attack-taxii.mitre.org/api/v21/")
```

---

## [MITRE] Normalizer の処理順序不備による Tactic-Technique 紐付け欠落

**現象**: `mitre_technique_tactic_map` のレコードが約半数しか登録されない。

**原因**: `mitre_raw_staging` から type 混在のまま1パスで処理すると、`attack-pattern`(technique)の処理時点で対応する `x-mitre-tactic` がまだ登録されておらず、`tactic_key` によるJOINが失敗して紐付けが欠落する。

**解決**: 2パス構成にする。Pass 1 で全 tactic を処理してから、Pass 2 で technique を処理する。

```python
# Pass 1: tactic を先にすべて処理
for row_id, obj_type, obj in parsed_rows:
    if obj_type == "x-mitre-tactic":
        ...

# Pass 2: technique を処理(この時点で tactic は全部揃っている)
for row_id, obj_type, obj in parsed_rows:
    if obj_type == "attack-pattern":
        ...
```

---

## [MariaDB] innodb_buffer_pool_size デフォルト値によるコンテナクラッシュ

**現象**: MITRE collector の初回実行(25,843件の一括INSERT)後、`mariadb-galera-0` が SIGABRT(Exit Code 133)でクラッシュ。

**原因**: コンテナのメモリ上限が 512Mi であるのに対し、`innodb_buffer_pool_size` のデフォルト値が 1GB に設定されており、平常時から利用可能メモリの 80〜90% を消費していた。大量INSERTでメモリを使い切りOOMKillが発生。

**解決**: `mariadb-values.yaml` の `mariadbConfiguration` で明示的に抑制する。

```ini
innodb_buffer_pool_size=256M
```

> 注意: helm upgrade 時のキー名は `config` ではなく `mariadbConfiguration` が正しい。`config` を使うと設定が無視される。

---

## [Monitoring] prometheus-operator が admission webhook の tls-secret 不在で起動できない

**現象**: kube-prometheus-stack をデプロイすると prometheus-operator Pod が起動せず、`secret "...-admission" not found` で待ち続ける。

**原因**: PrometheusRule 検証用の admission webhook は、証明書生成 Job (`admission-create`) が tls-secret を作ることで成立する。この Job が環境要因で失敗すると secret が作られず、operator が secret を要求し続けて起動できない。

**解決**: POC / プライベートクラスタでは admission webhook を無効化する（Prometheus/Grafana の動作には影響しない）。`monitoring/monitoring-values.yaml` に以下を指定する。

```yaml
prometheusOperator:
  admissionWebhooks:
    enabled: false
    patch:
      enabled: false
  tls:
    enabled: false
```

> 注意: `admissionWebhooks.enabled: false` と `patch.enabled: false` だけでは不十分。operator 側が tls-secret を要求し続けるため `tls.enabled: false` も必須（helm-charts issue #19147 / #1438）。
