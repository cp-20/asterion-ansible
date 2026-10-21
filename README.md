# Asterion Ansible

## ReadStack のサービス終了

`read-stack` ロールは終了ページ専用の構成です。アプリの取得、`.env` の生成、
Supabase の起動、DB migration は実行しません。他のロールを実行しないよう、
反映時は専用 Playbook を使用します（この PR を作成・マージするだけでは反映されません）。
Docker Compose plugin 2.22 以降と `community.docker` が必要です。要件不足や
イメージ取得失敗は旧アプリ停止前の検証で検出します。

```shell
ansible-playbook -i inventory/hosts.yaml project/retire-read-stack.yaml --limit plexus --ask-vault-pass
```

実行前・マージ前に、現在の Cloudflare の転送先がこのホストの 3000 / 8000 / 4173 番
ポートであることと、別ホスト・別 Compose・systemd・cron・外部ジョブに ReadStack の
アプリや記事取得処理がないことを確認してください。このリポジトリだけでは現在の
オリジンや Supabase 側のジョブは確認できません。旧アプリを再起動する自動化も停止してください。
ReadStack と無関係なサービス、共有 PostgreSQL、Supabase のデータは停止・削除しません。

ロールはまず `web` / `server` / `swagger-viewer` が存在する場合に Compose の作業
ディレクトリ、project (`read-stack`)、サービスのラベルを検証します。所有者が一致しなければ停止前に失敗します。
`/srv/read-stack` と project の両方が一致する全コンテナを検査し、既知のサービス
(`web` / `server` / `swagger-viewer`) 以外があれば、停止・ファイル変更前に中断します。
DB や独立 worker などの未知のサービスは、役割とデータ保持を確認してから明示的に
設計へ反映する必要があります。静的設定の配置・Compose 設定検証・イメージ取得を
停止前に済ませ、既知サービスの全コンテナ（追加のレプリカも含む）を停止し、
再起動ポリシーを無効にします。コンテナ・ボリューム・DB・記事・`.env` は削除しません。
旧 `docker-compose-deploy.yaml` はバックアップを残して空のサービス定義に置換します。

終了ページと設定は `/srv/read-stack-retired` に配置します。3000 / 4173 番は日本語の
終了ページ、8000 番の全経路と 3000 / 4173 番の `/api` 以下は JSON の HTTP 410 を
返します。静的サービスは DB 接続、API プロキシ、秘密情報、アプリコードを持ちません。
ポートの既存の公開範囲は引き継ぐため、別ホストの公開経路は別途確認が必要です。

反映後は旧コンテナがすべて停止し再起動ポリシーが `no` であること、旧ジョブや監督
プロセスが再生成しないこと、公開ドメインの終了ページ・旧 API の 410・別公開ルートを
確認してください。所有ラベルがないコンテナ、別 project、別ポートの旧プロセスは自動で停止しません。

ロールバックは静的 Compose を `stop` してポートを解放し、旧 Compose のバックアップを
元の場所へ復元したうえで、以前のコードと設定で起動する手順です。元のコンテナと
データは保持されます。ただし旧バックエンドを再公開すると既知の DoS 問題も戻るため、
明示的な判断なしにアプリを再起動しないでください。終了ページの修正だけなら静的構成を
修正して専用 Playbook を再実行できます。アプリ復帰を選択した場合は、この Ansible
変更も revert するか旧リビジョンを使用してください。変更後の通常の `task deploy`
も終了用ロールを実行するため、そのままでは再びアプリが停止します。

ローカル検証（本番 inventory・Vault を使わず、使い捨てコンテナと一時ポートだけを使用）:

```shell
ansible-playbook -i plexus, project/retire-read-stack.yaml --syntax-check
docker compose -f project/roles/read-stack/templates/docker-compose-deploy.yaml.j2 config --quiet
# Python 環境に ansible-core / requests / PyYAML と community.docker が必要
python tests/read-stack-retirement.py
```

## 使用しているポート

- 3000 (read-stack)
- 4173 (read-stack)
- 5984 (obsidian-livesync)
- 8000 (read-stack)
- 9000 (traq-ing)
- 10000 (wiki-js)
- 10443 (wiki-js)

## 環境

```
Task version: v3.27.1 (h1:cftsoOqUo7/pCdtO7fDa4HreXKDvbrRhfhhha8bH9xc=)
```

```
ansible [core 2.16.2]
  config file = None
  configured module search path = ['/home/cp20/.ansible/plugins/modules', '/usr/share/ansible/plugins/modules']
  ansible python module location = /home/cp20/.local/lib/python3.11/site-packages/ansible
  ansible collection location = /home/cp20/.ansible/collections:/usr/share/ansible/collections
  executable location = /home/cp20/.local/bin/ansible
  python version = 3.11.6 (main, Oct  2 2023, 13:45:54) [GCC 11.4.0] (/home/linuxbrew/.linuxbrew/opt/python@3.11/bin/python3.11)
  jinja version = 3.1.2
  libyaml = True
```

## 実行方法

```
task deploy
```

