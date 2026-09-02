# pyinfra インベントリ（将来の SSH 実行用・現状は未使用）
#
# 【重要】ミニマムスタート版は制御ノード上での @local 実行に限定しており、
# このインベントリは使用しない（deploy-design.md 第3章）。
#   実行方法:  pyinfra @local deploy_cluster.py
#
# このファイルは、将来 SSH 越し実行をサポートする際の接続先定義として
# 残してある布石。SSH 実行には values / SQL / kustomize ツリーを対象ホストへ
# 転送する仕組み（files.put / files.rsync）が別途必要（第9章の今後の課題）。
#
# 以下の IP / ユーザーは自環境の例。SSH 実行を実装する際に書き換える。

k3s_master = [
    (
        "192.168.64.10",
        {
            "ssh_user": "kamonabe",
        },
    ),
]
