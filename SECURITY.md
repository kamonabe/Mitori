# セキュリティ評価・改善項目

最終更新: 2026-08-06

対応済みの良い点と、今後対応すべき改善項目を記録する。

---

## ✅ 対応済み

- **Secret管理**: DB接続情報・Slack Webhook URLはすべてKubernetes Secretから環境変数で渡し、マニフェスト・コードへのハードコードなし
- **SQLインジェクション対策**: 全SQLクエリでプレースホルダー(`%s`)によるパラメータバインディングを徹底
- **イメージタグ固定**: `:latest` を使わず固定タグを指定(`mitre-python:1.0.0`、`alpine/curl:8.19.0` 等)
- **外部API通信のタイムアウト設定**: 全 `requests` 呼び出しに `timeout` を設定し、無限ブロックを防止
- **コンテナのセキュリティコンテキスト設定**: 全CronJobに `runAsNonRoot`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: ALL` を設定。Pythonコンテナには `PYTHONDONTWRITEBYTECODE=1` を合わせて設定し `.pyc` 書き込みを抑止

---

## ⚠️ 改善項目

### [LOW] mirror-check の一部ミラーURLがHTTP

**対象**: `mirror-check-cronjob.yaml` の `MIRROR_1`(山形大)、`MIRROR_2`(IIJ)

**状況**: ミラーURLが `http://` で記載されているが、これはFedoraのmirrorlist/metalinkがHTTP形式のURLを返すためであり、監視スクリプトはこのリストとの一致比較を行う仕組み上、HTTPのまま維持する必要がある。

**補足**:
- 各ミラーサイト自体はHTTPS対応済み(2026-08-06確認済み)
- しかしFedoraの `mirrors.fedoraproject.org/mirrorlist` が返すURLはHTTP形式のため、スクリプト側をHTTPSに変更すると一致判定が失敗する
- dnfのデフォルト設定(`metalink`経由)でも、最終的なパッケージダウンロードはHTTPで行われる(RPMのGPG署名により改ざんは検知可能)
- 現環境はUTM仮想ネットワーク内に閉じており、傍受リスクは実質ゼロ

**結論**: 対応不要。Fedora側のmirrorlistがHTTPS URLを返すようになれば自動的に解消されるが、現時点ではスクリプト側で対応する手段がない。

---

### [LOW] `mitre_raw_staging` 処理済みレコードの無期限蓄積

**対象**: `mitre_raw_staging` テーブル

**対応済み（2026-08-07）**: `normalizer.py` の `cleanup_old_processed()` で、処理完了から7日以上経過したレコードを自動削除するようにした。normalizer の毎回の実行末尾で呼ばれるため、別途CronJobは不要。

---

### [INFO] `ghcr-secret` (GitHub PAT) の有効期限管理

**対象**: `ghcr-secret` Secret（`app` namespace）

**概要**: GHCR からのイメージ Pull に使用する `docker-registry` 型 Secret。GitHub Personal Access Token (PAT) を認証情報として含む。

**PAT の要件**:
- スコープ: `read:packages`（最小権限）
- 種類: Fine-grained PAT 推奨（Classic PAT でも動作する）

**有効期限と更新手順**:

1. GitHub Settings → Developer settings → Personal access tokens でトークンの有効期限を確認
2. 期限切れ前に新しい PAT を発行
3. 既存 Secret を削除して再作成:

```bash
kubectl delete secret ghcr-secret -n app

kubectl create secret docker-registry ghcr-secret -n app \
  --docker-server=ghcr.io \
  --docker-username='<GitHubユーザー名>' \
  --docker-password='<新しいPAT>' \
  --docker-email='<メールアドレス>'
```

4. 既に稼働中の CronJob は次回起動時に新しい Secret を自動参照する（Pod 再起動不要）

**期限切れ時の症状**:
- CronJob の Pod が `ImagePullBackOff` になる
- `kubectl describe pod <pod名> -n app` で `unauthorized: authentication required` エラーが確認できる

**運用上の注意**:
- Classic PAT で「No expiration」を選択した場合は期限管理不要だが、セキュリティ上は有期限 + 定期ローテーションが望ましい
- 現環境は個人利用の閉じた環境のため、有効期限なし PAT でも許容する判断としている
