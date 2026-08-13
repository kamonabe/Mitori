# Mitori ロードマップ

最終更新: 2026-08-12

今後の改善案・課題を一元管理するドキュメントです。

## cve-watch

- [x] 通知フォーマット改善: アクション明示（「helm upgradeで対応可能」等）、参照URL付与
- [x] published日フィルタ: 古いCVE（1年以上前）は通知スキップ、DBには記録
- [x] 初回大量検知の特別扱い: 初回はサマリのみ、2回目以降から差分通知
- [x] 重大度フィルタ: `CVE_NOTIFY_MIN_SEVERITY` 環境変数で通知閾値を設定可能
- [ ] GHSAソース優先: 人間が読める重大度（HIGH/CRITICAL等）を確実に取得
- [ ] NVD API対応: MariaDB等、OSVにデータがないソフトウェアをカバー（API Key取得が必要）
- [ ] 週次サマリ通知: 未対処CVE一覧を週1で通知するオプション
- [ ] ATT&CK連携: CVEのCWE → MITRE ATT&CKテクニック紐付け（mitre-normalizerのデータ参照）
- [ ] Grafanaダッシュボード: 未対処CVE数、検知推移をパネル化
- [ ] semverによる自動クローズ: OSV API再クエリではなくローカルでバージョン比較

## inventory-scan

- [ ] ホストOS/カーネル情報の収集: OS依存の取得方法を抽象化する設計が必要
- [ ] コンテナイメージのダイジェスト形式対応: `image:v0.91.0@sha256:...` のパース改善
- [ ] lifecycle-notifyとの統合: inventoryのバージョン + eol-watchのEOL日で「EOL接近」を自動判定

## eol-watch

- [ ] 差分なしの場合は通知しない運用への変更（毎回の定期チェック通知がノイジー）

## mirror-check

- [ ] 監視対象ミラー数の可変化: 現在3固定。環境変数の渡し方を変更して増減対応

## 新規サービス

- [x] KEV (Known Exploited Vulnerabilities): CISA KEVカタログ取得 + cve-watchとの突合通知
- [ ] EPSS連携: CVE/KEVにExploit Prediction Scoring Systemスコアを付加して優先度精緻化
- [ ] Drift Detector: Git上マニフェスト vs 実クラスタの差分検知
- [ ] Backup Verifier: MariaDBバックアップのリストア検証
- [ ] Certificate/Secret Expiry Watcher: TLS証明書・Secretの有効期限監視
- [ ] Dependency Update Notifier: コンテナイメージ/Helmチャート/pipの新バージョン通知

## ディストロ選定支援 (distro-pulse)

Linuxディストリビューション選定の判断材料を定期収集・通知するアイデア。
「次にサーバーを立てるときにどのディストロを選ぶか」の意思決定を継続的に支援する。

### 今できること（endoflife.date API）

- [x] 主要ディストロのEOL情報を eol-watch の `monitor_targets` に追加して定期収集
  - 対象: AlmaLinux, Rocky Linux, Ubuntu, Debian, Fedora 等
  - サポート期間の変更・新バージョンリリースを検知→Slack通知
  - CentOS的な「突然のEOL前倒し」の早期検知に寄与

### 将来やりたいこと（現時点で信頼できる公開APIが存在しない）

- [ ] サーバー用途Linuxディストロのシェア率・採用率の定期取得
  - 条件: 規約的にクリーンな公開APIのみ利用（スクレイピング不可）
  - 条件: バイアスのかかった情報源は不可（ゲーマー向け統計等）
  - 条件: 万人が共通認識として判断できるデータであること
  - 現状: W3Techsは有料API、DistroWatchはAPI無し、Steam Surveyはバイアスあり
  - トリガー: 上記条件を満たす公開APIが登場した時点で再検討

## インフラ / CI

- [x] GitHub Actions: lint (ruff) + テスト (pytest) + マニフェスト検証 (kubeconform)
- [x] GitHub Actions: Dockerfile変更時にイメージビルド + ghcr.io push の自動化
- [x] Dependabot: pip / GitHub Actions / Docker のバージョン自動追跡
- [x] ブランチ保護: main直push禁止、CI必須、force push禁止
- [ ] inventory-scan の nodeSelector 除去: ghcr.io push 完了済み（対応済み）
