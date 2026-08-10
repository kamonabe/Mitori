# EPELミラー監視 設計ドキュメント

最終更新: 2026-08-06

## 1. 概要

パッケージ管理で使用しているEPEL(Extra Packages for Enterprise Linux)ミラーが、Fedoraの公式ミラーリストに引き続き掲載されているかを毎日確認するサービスです。ミラーがリストから外れた場合、`yum`/`dnf` のパッケージインストールが失敗するリスクがあるため、早期に検知してミラーを差し替えられるよう監視しています。

## 2. 監視対象ミラー

| 変数 | URL | プロトコル |
|---|---|---|
| `MIRROR_1` | `http://ftp.yz.yamagata-u.ac.jp/pub/linux/fedora-projects/epel/10.3/Everything/aarch64/` | HTTP |
| `MIRROR_2` | `http://ftp.iij.ad.jp/pub/linux/Fedora/epel/10.3/Everything/aarch64/` | HTTP |
| `MIRROR_3` | `https://ftp.kaist.ac.kr/pub/epel/10.3/Everything/aarch64/` | HTTPS |

ミラーを変更する場合は `mirror-check-cronjob.yaml` の環境変数(`MIRROR_1`〜`MIRROR_3`)を更新し、`mirror-check-configmap.yaml` は変更不要。

> MIRROR_1・MIRROR_2 は HTTP で記載しているが、これはFedoraのmirrorlistがHTTP形式のURLを返すためであり、一致比較の都合上HTTPのまま維持する必要がある。ミラーサイト自体はHTTPS対応済み(2026-08-06確認済み)。詳細は `SECURITY.md` を参照。

## 3. 処理フロー

```
Fedora 公式ミラーリストを取得
https://mirrors.fedoraproject.org/mirrorlist?repo=epel-10&arch=aarch64
        ↓
各監視対象ミラーのURLがリストに含まれるか確認
        ↓
欠落数に応じてアラートレベルを判定
        ↓
NORMAL以外 → Slack通知 + 終了コードを返す
```

## 4. アラートレベル

欠落数(監視対象ミラーのうちリストに載っていない件数)に応じて4段階で判定します。

| 欠落数 | レベル | 終了コード | Slack通知 | 対応方針 |
|---|---|---|---|---|
| 0 | NORMAL | 0 | なし | 対応不要 |
| 1 | WARN | 1 | あり(:warning:) | 次回棚卸し時に確認 |
| 2 | ALERT | 2 | あり(:rotating_light:) | 早めにミラーを差し替え |
| 3以上 | CRITICAL | 3 | あり(:sos:) | 至急対応(インストール不能の可能性) |

終了コードが0以外でもCronJobとしては「失敗」と扱わない設計にするため、`backoffLimit: 0`(リトライなし)を設定しています。NG検知が目的のジョブのため再実行しても意味がないためです。

## 5. 比較ロジック

末尾スラッシュの有無による不一致を防ぐため、ミラーURLとミラーリストの両方から末尾スラッシュを除去してから `grep -F`(完全文字列一致)で比較しています。

```sh
normalized="${mirror%/}"
echo "${MIRROR_LIST}" | sed 's|/$||' | grep -qF "${normalized}"
```

## 6. スクリプトの2種類について

| ファイル | 用途 | シェル |
|---|---|---|
| `mirror-check-configmap.yaml` 内の `check-epel-mirrors.sh` | CronJob実行用(ConfigMap経由でPodにマウント) | `sh`(POSIX sh) |
| `check-epel-mirrors.sh` | ローカル手動実行用 | `bash`(色付き出力対応) |

ConfigMap版は `alpine/curl` イメージ上で動作するため `bash` が使えず POSIX `sh` で記述しています。ローカル版は `bash` の配列・色定義を活用しています。ロジックは同一です。

## 7. インフラ構成

- **スケジュール**: 毎日 `09:00 UTC`
- **イメージ**: `alpine/curl:8.19.0`（Docker Hub の public image）
- **imagePullSecrets**: なし（public image のため認証不要。規約では `ghcr-secret` を指定するルールだが、本サービスは ghcr.io を使用しないため適用外）
- **ConfigMap**: `mirror-check-script`
- **Secret**: `mirror-check-slack`（webhook-url）
- **backoffLimit**: `0`（リトライなし）

## 8. ミラー変更手順

監視対象ミラーを追加・変更する場合:

1. [Fedora Mirror Manager](https://mirrors.fedoraproject.org/) で新しいミラーがリストに掲載されていることを確認
2. `mirror-check-cronjob.yaml` の `MIRROR_1`〜`MIRROR_3` を更新
3. `kubectl apply -f mirror-check/mirror-check-cronjob.yaml -n app` で反映
4. ローカルで `check-epel-mirrors.sh` を手動実行して動作確認

## 9. 今後の課題

[ROADMAP.md](../ROADMAP.md) で一元管理しています。
