# CI 境界定義

最終更新: 2026-08-10

## 目的

CIが自動で保証する範囲と、手動確認に委ねる範囲を明示する。
改修・拡張時に「これはCIに含めるべきか？」の判断基準として使う。

> この定義は現時点のスナップショットであり、環境やチーム状況に応じて更新する。

---

## CI が保証するもの

| チェック | ジョブ | 何を担保するか |
|---|---|---|
| Lint | `lint-and-test` | コードの静的品質（ruff check） |
| Format | `lint-and-test` | フォーマット統一（ruff format --check） |
| ユニットテスト | `lint-and-test` | 純粋ロジックの正しさ（pytest + mock） |
| カバレッジ計測 | `lint-and-test` | テスト対象の可視化（閾値ゲートなし） |
| マニフェスト検証 | `validate-manifests` | K8sリソース定義の構文・スキーマ正当性（kubeconform） |
| イメージビルド | `build-images` | Dockerfile変更時にビルド可能であること |

## CI が保証しないもの（手動確認の範囲）

| 対象 | 理由 | 確認方法 |
|---|---|---|
| DB統合テスト（実MariaDB） | CIにDB環境を持たない | ローカル or クラスター上で手動実行 |
| CronJob結合動作 | スケジュール実行・Pod起動はクラスター依存 | `kubectl create job --from=cronjob/<name>` で手動確認 |
| シェルスクリプト（mirror-check等） | pytestの守備範囲外 | クラスター上で手動実行 |
| 外部API疎通 | ネットワーク・認証依存。CI環境ではrate limit等の問題 | ローカル実行で確認 |
| デプロイ | 本番反映は人の判断が必要 | `kubectl apply -k .` を手動実行 |
| Helmリリース更新 | values変更の影響範囲が大きい | `helm diff` で差分確認後に手動適用 |

## 将来的にCIへ取り込みたいもの

| 対象 | 前提条件 | 優先度 |
|---|---|---|
| DB統合テスト | docker-compose or GitHub Actions service container導入 | 中 |
| shellcheck（mirror-check等） | shellcheck導入 | 低 |
| カバレッジ閾値ゲート | 対象が安定してから設定 | 低 |

## 判断基準

新しいチェックをCIに追加するかの判断:

1. **再現性**: CI環境（ubuntu-latest）で安定して再現できるか？
2. **速度**: ジョブ全体を大幅に遅くしないか？（目安: +30秒以内）
3. **価値**: 手動で見逃しやすく、壊れたときの影響が大きいか？

3つすべてYesなら追加する。どれか欠ければ手動確認に残す。
