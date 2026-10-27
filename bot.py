import asyncio
import io
import logging
import os
import re
import shlex

import discord
from discord import app_commands
from dotenv import load_dotenv

MAX_FILE_SIZE = 20 * 1024 * 1024
SCHEMATICS_DIR = '/home/exruser/minecraft/servers/thelow-dev1/plugins/WorldEdit/schematics'


def validate_filename(filename: str) -> None:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:schem|schematic)', filename, re.IGNORECASE):
        raise ValueError('ファイル名は英数字、ハイフン、アンダースコア、ピリオドのみで、拡張子は .schem または .schematic にしてください。')


def ssh_arguments(command: str, key_path: str, bastion_mode: bool) -> list[str]:
    common = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15']
    if bastion_mode:
        return common + ['-i', os.path.expanduser(key_path), '-p', '2004', 'exruser@27.83.78.98', command]
    inner = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-i', '~/.ssh/id_ed25519', '-p', '2004', 'exruser@27.83.78.98', command]
    remote = ' '.join('~/.ssh/id_ed25519' if arg == '~/.ssh/id_ed25519' else shlex.quote(arg) for arg in inner)
    return common + ['-i', os.path.expanduser(key_path), 'ubuntu@140.227.29.232', remote]


async def run_ssh(command: str, key_path: str, bastion_mode: bool, data: bytes | None = None) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *ssh_arguments(command, key_path, bastion_mode),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(data), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError('SSH 転送がタイムアウトしました。')
    if process.returncode:
        logging.error('SSH transfer failed: %s', stderr.decode(errors='replace')[:2000])
        raise RuntimeError('SSH 転送に失敗しました。Bot のログを確認してください。')
    return stdout


async def transfer_file(filename: str, data: bytes, key_path: str, bastion_mode: bool) -> None:
    validate_filename(filename)
    upload = shlex.quote('/home/exruser/upload/' + filename)
    destination = shlex.quote('/home/exruser/minecraft/servers/thelow-dev1/plugins/WorldEdit/schematics/' + filename)
    command = f'umask 077; set -C; cat > {upload} && cat {upload} > {destination}'
    await run_ssh(command, key_path, bastion_mode, data)


async def download_file(filename: str, key_path: str, bastion_mode: bool) -> bytes:
    validate_filename(filename)
    source = shlex.quote(f'{SCHEMATICS_DIR}/{filename}')
    size = await run_ssh(f'test -f {source} && stat -c %s -- {source}', key_path, bastion_mode)
    try:
        byte_count = int(size.decode().strip())
    except ValueError as exc:
        raise RuntimeError('サーバー上のファイルサイズを取得できませんでした。') from exc
    if byte_count > MAX_FILE_SIZE:
        raise ValueError('ファイルは 20 MiB を超えているため Discord に送信できません。')
    data = await run_ssh(f'cat -- {source}', key_path, bastion_mode)
    if len(data) != byte_count:
        raise RuntimeError('ダウンロード中にファイルサイズが変わりました。もう一度お試しください。')
    return data


async def list_schematics(key_path: str, bastion_mode: bool) -> bytes:
    directory = shlex.quote(SCHEMATICS_DIR)
    return await run_ssh(f"find {directory} -maxdepth 1 -type f \\( -iname '*.schem' -o -iname '*.schematic' \\) -printf '%f\\n' | sort", key_path, bastion_mode)


class TransferBot(discord.Client):
    def __init__(self, guild_id: int | None) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.guild_id = guild_id

    async def setup_hook(self) -> None:
        if self.guild_id is not None:
            guild = discord.Object(id=self.guild_id)
            self.tree.copy_global_to(guild=guild)
            commands = await self.tree.sync(guild=guild)
            logging.info('Synced %d commands to guild %s', len(commands), self.guild_id)
        else:
            commands = await self.tree.sync()
            logging.info('Synced %d global commands', len(commands))

    async def on_ready(self) -> None:
        logging.info('Logged in as %s (ID: %s)', self.user, self.user.id)


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    token = os.getenv('DISCORD_TOKEN', '').strip()
    if not token:
        raise SystemExit('DISCORD_TOKEN が設定されていません。.env を確認してください。')
    guild_id_text = os.getenv('DISCORD_GUILD_ID', '').strip()
    if guild_id_text and (not guild_id_text.isascii() or not guild_id_text.isdecimal() or int(guild_id_text) <= 0):
        raise SystemExit('DISCORD_GUILD_ID にはサーバー ID の数字を指定してください。')

    bot = TransferBot(int(guild_id_text) if guild_id_text else None)

    @bot.tree.command(name='ping', description='Bot の動作を確認します')
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message('起動しています！', ephemeral=True)

    @bot.tree.command(name='upload', description='ファイルを受け取って確認します')
    @app_commands.describe(file='送信するファイル')
    async def upload(interaction: discord.Interaction, file: discord.Attachment) -> None:
        key_path = os.getenv('BASTION_SSH_KEY', '').strip()
        if not key_path:
            await interaction.response.send_message('SSH 秘密鍵の設定がありません。')
            return
        if file.size > MAX_FILE_SIZE:
            await interaction.response.send_message('ファイルは 20 MiB 以下にしてください。')
            return
        await interaction.response.defer(thinking=True)
        try:
            data = await file.read()
        except discord.HTTPException:
            logging.exception('Failed to download attachment')
            await interaction.followup.send('ファイルを取得できませんでした。もう一度お試しください。')
            return
        try:
            bastion_mode = os.getenv('BASTION_MODE', '').strip().lower() in {'1', 'true', 'yes'}
            await transfer_file(file.filename, data, key_path, bastion_mode)
        except (ValueError, RuntimeError, OSError) as exc:
            logging.warning('Upload failed: %s', exc)
            await interaction.followup.send(str(exc))
            return
        await interaction.followup.send(
            f'転送しました: {discord.utils.escape_markdown(file.filename)}\nサイズ: {len(data):,} バイト',
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @bot.tree.command(name='download', description='サーバー上の schematic をダウンロードします')
    @app_commands.describe(filename='取得する .schem または .schematic のファイル名')
    async def download(interaction: discord.Interaction, filename: str) -> None:
        key_path = os.getenv('BASTION_SSH_KEY', '').strip()
        if not key_path:
            await interaction.response.send_message('SSH 秘密鍵の設定がありません。', ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            bastion_mode = os.getenv('BASTION_MODE', '').strip().lower() in {'1', 'true', 'yes'}
            data = await download_file(filename, key_path, bastion_mode)
        except (ValueError, RuntimeError, OSError) as exc:
            logging.warning('Download failed: %s', exc)
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send(
            f'ダウンロードしました: {discord.utils.escape_markdown(filename)}',
            file=discord.File(io.BytesIO(data), filename=filename), ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @bot.tree.command(name='schematics', description='サーバー上の schematic 名一覧を取得します')
    async def schematics(interaction: discord.Interaction) -> None:
        key_path = os.getenv('BASTION_SSH_KEY', '').strip()
        if not key_path:
            await interaction.response.send_message('SSH 秘密鍵の設定がありません。', ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            bastion_mode = os.getenv('BASTION_MODE', '').strip().lower() in {'1', 'true', 'yes'}
            names = await list_schematics(key_path, bastion_mode)
        except (RuntimeError, OSError) as exc:
            logging.warning('Schematic listing failed: %s', exc)
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        if not names:
            await interaction.followup.send('schematic はありません。', ephemeral=True)
        elif len(names) <= 1_800:
            await interaction.followup.send(f'```text\n{names.decode(errors="replace")}```', ephemeral=True)
        else:
            await interaction.followup.send('一覧を添付します。', file=discord.File(io.BytesIO(names), filename='schematics.txt'), ephemeral=True)

    bot.run(token, log_handler=None)


if __name__ == '__main__':
    main()
