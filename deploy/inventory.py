# pyinfra インベントリ（ミニマムスタート版）
#
# デプロイ対象ホストを定義する。
# 実行元ホストから SSH でクラスタ制御ノードに接続する想定（実行元の OS は不問）。
# 以下の IP / ユーザーは自環境の例。別環境ではこの値を書き換える。
#
# 使い方:
#   pyinfra inventory.py deploy_cluster.py
#
# 接続先やユーザーは環境に合わせて書き換えること。
# ローカル（制御ノード上で直接実行）する場合は @local を使う:
#   pyinfra @local deploy_cluster.py

k3s_master = [
    (
        "192.168.64.10",
        {
            "ssh_user": "kamonabe",
        },
    ),
]
