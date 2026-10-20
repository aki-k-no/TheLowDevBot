import asyncio
import logging
import os
import re
import shlex

import discord
from discord import app_commands
from dotenv import load_dotenv


async def transfer_file(filename: str, data: bytes, key_path: str, bastion_mode: bool) -> None:
    # Restrict the name before inserting it into a command executed by the remote shell.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(?:schem|schematic)', filename, re.IGNORECASE):
        raise ValueError('ファイル名は英数字、ハイフン、アンダースコア、ピリオドのみで、拡張子は .schem または .schematic にしてください。')
    upload = shlex.quote('/home/exruser/upload/' + filename)
    destination = shlex.quote('/home/exruser/minecraft/servers/thelow-dev1/plugins/WorldEdit/schematics/' + filename)
    command = f'umask 077; set -C; cat > {upload} && cat {upload} > {destination}'
    if bastion_mode:
        ssh_args = [
            'ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-i', os.path.expanduser(key_path), '-p', '2004', 'exruser@27.83.78.98', command,
        ]
    else:
        inner = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-i', '~/.ssh/id_ed25519', '-p', '2004', 'exruser@27.83.78.98', command]
        # Leave the remote key path unquoted so the bastion shell expands ~.
        remote = ' '.join('~/.ssh/id_ed25519' if arg == '~/.ssh/id_ed25519' else shlex.quote(arg) for arg in inner)
        ssh_args = [
            'ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15',
            '-i', os.path.expanduser(key_path), 'ubuntu@140.227.29.232', remote,
        ]
    process = await asyncio.create_subprocess_exec(
        *ssh_args,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(data), timeout=120)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError('SSH 転送がタイムアウトしました。')
    if process.returncode:
        logging.error('SSH transfer failed: %s', stderr.decode(errors='replace')[:2000])
        raise RuntimeError('SSH 転送に失敗しました。Bot のログを確認してください。')


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
        if file.size > 20 * 1024 * 1024:
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

    bot.run(token, log_handler=None)


if __name__ == '__main__':
    main()
