# Asterion Ansible

## ReadStack の終了ページ

Ansible は `/srv/read-stack-retired` に静的ファイルを配置し、Nginx を起動するだけです。
3000 / 4173 番は終了案内と `contact@cp20.dev` へのリンク、8000 番の全経路と
他ポートの `/api` 以下は HTTP 410 を返します。DB・保存データ・`.env`・旧 Compose は変更しません。

### 旧アプリの停止（別途手動で実行）

1. Cloudflare の転送先、旧アプリ・API・背景処理、別ホストや別公開ルートを確認します。
   コンテナは Compose の project・作業ディレクトリ・service を照合し、ReadStack のアプリだけを特定してください。
2. 確認したアプリのコンテナ ID に対して、必要に応じて `docker update --restart=no <ID...>`、
   `docker stop <ID...>` を実行します。systemd・cron などの再起動元と独立ジョブも個別に止めます。
   DB や無関係なコンテナは止めず、ボリューム・記事・秘密情報を削除しないでください。
3. 3000 / 8000 / 4173 番の競合が解消されたことを確認してから、終了ページを起動します。

### 終了ページの配置・起動

Docker Compose plugin と `community.docker` が必要です。他のロールを実行しない専用 Playbook:

```shell
ansible-playbook -i inventory/hosts.yaml project/retire-read-stack.yaml --limit plexus --ask-vault-pass
```

公開ドメインの終了ページと旧 API の 410、別経路から旧バックエンドに到達しないことを確認してください。
PR の作成・マージだけでは反映されません。Ansible は旧アプリの停止やポート競合の解消を行いません。

ロールバック時は `/srv/read-stack-retired/compose.yaml` の静的サービスを `docker compose -p read-stack-retired -f /srv/read-stack-retired/compose.yaml stop` で止めます。
旧アプリとデータは保持されますが、旧アプリの再公開は既知の問題を戻すため、明示的に判断してください。

ローカル検証（本番 inventory・Vault は使用しません）:

```shell
ansible-playbook -i plexus, project/retire-read-stack.yaml --syntax-check
python tests/read-stack-retirement.py  # PyYAML とローカル Docker が必要
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

