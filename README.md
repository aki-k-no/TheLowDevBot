# Discord Drive Transfer Bot

Discord で受け取った schematic ファイルを踏み台経由で SSH 転送する Bot です。

## セットアップ（Windows / PowerShell）

Python 3.10 以降を用意し、このフォルダーで次を実行します。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作成し、Bot のトークンを取得します。
2. `.env` の `DISCORD_TOKEN` にトークンを設定します。トークンは他人に共有せず、Git にコミットしないでください。
3. 開発中は `DISCORD_GUILD_ID` にテスト用サーバーの ID を設定します。Discord の開発者モードを有効にしてサーバーを右クリックすると ID をコピーできます。空欄ならグローバル登録されますが、反映に時間がかかることがあります。
4. Developer Portal の Installation 設定でサーバーへのインストールを有効にし、`bot` と `applications.commands` のスコープを設定して、生成されたリンクから Bot をサーバーに追加します。

```powershell
.\.venv\Scripts\python.exe bot.py
```

Discord で `/ping` を実行し、「起動しています！」と表示されれば成功です。停止するときは PowerShell で `Ctrl+C` を押します。メッセージ内容の読み取り権限など、特別な Gateway Intent は必要ありません。

## SSH 転送の準備

`.env` に次の設定を追加します（既存のトークンは残します）。Bot を導入したサーバーで `/upload` を使えるユーザーが転送できます。

```env
BASTION_SSH_KEY=C:/Users/yourname/.ssh/bastion_key
```

### 踏み台サーバー上で動かす場合

Bot 一式を踏み台に配置して起動する場合は、`.env` を次のように設定します。`BASTION_SSH_KEY` は踏み台から本番サーバーへ接続する鍵で、通常は `~/.ssh/id_ed25519` です。このモードでは Windows から踏み台へ接続する処理を行いません。

```env
BASTION_MODE=true
BASTION_SSH_KEY=/home/ubuntu/.ssh/id_ed25519
```

本番サーバーのホスト鍵は、Bot を起動する `ubuntu` ユーザーの `~/.ssh/known_hosts` に登録してください。常駐させるなら、踏み台で `screen -S discord-transfer` を開始して Bot を実行し、`Ctrl+A` の後に `D` でデタッチできます。再接続は `screen -r discord-transfer` です。

Windows の OpenSSH クライアントが必要です。Bot は対話形式のパスフレーズ入力に対応しないため、必要なら SSH エージェントを利用してください。事前に PowerShell から次のように接続し、管理者から別経路で入手したホスト鍵の指紋を照合して `known_hosts` に登録してください。続いて踏み台上から本番サーバーへ接続して同様に確認します。

```powershell
ssh -i C:/Users/yourname/.ssh/bastion_key ubuntu@140.227.29.232
```

```sh
ssh -i ~/.ssh/id_ed25519 -p 2004 exruser@27.83.78.98
```

本番サーバー上の `/home/exruser/upload` と `/home/exruser/minecraft/servers/thelow-dev1/plugins/WorldEdit/schematics` は事前に作成し、`exruser` に書き込み権限を付けてください。Bot を再起動し `/upload` の `file` にファイルを添付すると、upload に送った後、schematics にコピーします。ファイル名は英数字、`.`、`_`、`-` のみ、拡張子は `.schem` または `.schematic` に限ります。Bot の受信上限は 20 MiB です。同名ファイルは上書きしません。途中で失敗すると upload 側にファイルが残る場合があるため、ログと両方のフォルダーを確認してから再試行してください。

`/schematics` は本番サーバーの schematic 名一覧を取得します。`/download filename:<ファイル名>` はそのファイルを Discord に添付して返します。どちらも実行した本人だけに表示され、`.schem` / `.schematic` のみ、20 MiB 以下が対象です。

## 踏み台（Linux）へ Git で配置する

踏み台で Python 3.10 以降と Git を用意してから、リポジトリを取得します。`requirements.txt` には Bot の Python 依存関係をすべて記載しています。標準の Python が古い Linux では、先に Python 3.10 以降を導入してください。

```bash
git clone <リポジトリURL> discord-transfer-bot
cd discord-transfer-bot
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

`.env` に Discord のトークンと踏み台モードの設定を書き込んでから、次で起動します。

```bash
.venv/bin/python bot.py
```

更新時は Bot を停止し、同じディレクトリで `git pull`、`.venv/bin/python -m pip install -r requirements.txt`、再起動の順に実行します。`.env`、`.venv/`、`keys/` は Git の管理対象外です。秘密鍵と Discord トークンはコミットしないでください。

## 次の実装候補

- Google Drive の認証とファイルの取得
