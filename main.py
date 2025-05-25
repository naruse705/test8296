import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import random
import gspread_asyncio
from oauth2client.service_account import ServiceAccountCredentials

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)
tree = bot.tree

recruitments = {}
allowed_channels = [1375690178651488308, 1375690144232771684, 1375690250030022720, 1375690271584419881, 1375690288592588903]
result_announcement_channel_id = 1375690877342584893
target_channel_id = 1375561728221249581

role_id = 1375690414287224842

EMBED_TITLE = "ゲームID登録"

def get_creds():
    return ServiceAccountCredentials.from_json_keyfile_name('creds.json', [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ])

agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)
agc = None
sheet = None

class GameIDModal(discord.ui.Modal, title="ゲームIDを入力してください"):
    gameid = discord.ui.TextInput(label="ゲームID", placeholder="例: 1234567890", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user_id = str(interaction.user.id)
        gameid_value = self.gameid.value

        try:
            worksheet = await sh.worksheet("id_list")
            data = await worksheet.get_all_values()

            updated = False
            for i, row in enumerate(data):
                if row and row[0] == user_id:
                    await worksheet.update_cell(i + 1, 2, gameid_value)
                    updated = True
                    break

            if not updated:
                await worksheet.append_row([user_id, gameid_value])

            guild = interaction.guild

            if guild:
                role = guild.get_role(role_id)
                if role:
                    await interaction.user.add_roles(role)
                else:
                    await interaction.followup.send("ロールが見つかりませんでした。", ephemeral=True)
                    return

            await interaction.followup.send(f"ゲームID `{gameid_value}` を登録し、ロールを付与しました。", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"登録中にエラーが発生しました: {e}", ephemeral=True)

class GameIDView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="登録", style=discord.ButtonStyle.primary, custom_id="register_game_id")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(GameIDModal())

def generate_unique_id():
    now = datetime.datetime.now()
    return f"game-{now.strftime('%y%m%d%H%M')}"

class RecruitmentView(discord.ui.View):
    def __init__(self, author_id, unique_id):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.unique_id = unique_id
        self.participants = [author_id]
        self.reported = []

    async def update_embed(self, interaction):
        guild = interaction.guild
        host_member = guild.get_member(self.author_id)
        host_display_name = host_member.display_name if host_member else f"<@{self.author_id}>"

        embed = discord.Embed(title="⚔️ 対戦募集", color=discord.Color.green())
        embed.add_field(name="ステータス", value=f"```募集中```", inline=False)
        embed.add_field(name="募集ID", value=f"```{self.unique_id}```", inline=False)
        embed.add_field(name="主催者", value=f"```{host_display_name}```", inline=True)
        embed.add_field(name="ホスト", value="``` ```", inline=True)
        embed.add_field(name="ホストゲームID", value="``` ```", inline=True)

        participants_display = "\n".join(f"<@{uid}>" for uid in self.participants)
        embed.add_field(name=f"参加者 {len(self.participants)}/10", value=participants_display, inline=True)

        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="参加", style=discord.ButtonStyle.success, custom_id="join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id in self.participants:
            await interaction.followup.send("既に参加しています。", ephemeral=True)
            return
        if len(self.participants) >= 10:
            await interaction.followup.send("参加人数が上限に達しています。", ephemeral=True)
            return
        self.participants.append(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="辞退", style=discord.ButtonStyle.danger, custom_id="leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id == self.author_id:
            await interaction.followup.send("主催者は辞退できません。", ephemeral=True)
            return
        if interaction.user.id not in self.participants:
            await interaction.followup.send("参加していません。", ephemeral=True)
            return
        self.participants.remove(interaction.user.id)
        await self.update_embed(interaction)

    @discord.ui.button(label="募集終了", style=discord.ButtonStyle.primary, custom_id="end")
    async def end(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.author_id:
            await interaction.followup.send("この操作は募集主のみが可能です。", ephemeral=True)
            return
        
        if len(self.participants) < 10:
            await interaction.followup.send("10名の参加が必要です。", ephemeral=True)
            return

        host_id = random.choice(self.participants)

        worksheet = await sh.worksheet("id_list")
        records = await worksheet.get_all_records()

        game_id = next((r["GameID"] for r in records if str(r["DiscordUserID"]) == str(host_id)), None)
        if not game_id:
            await interaction.followup.send("ホストのゲームIDが見つかりません。", ephemeral=True)
            return

        guild = interaction.guild
        host_member = guild.get_member(host_id)
        host_display_name = host_member.display_name if host_member else f"<@{host_id}>"

        organizer_member = guild.get_member(self.author_id)
        organizer_display_name = organizer_member.display_name if organizer_member else f"<@{self.author_id}>"

        # チーム分け
        shuffled = self.participants.copy()
        random.shuffle(shuffled)
        team_a = shuffled[:5]
        team_b = shuffled[5:]

        team_a_display = "\n".join(f"<@{uid}>" for uid in team_a)
        team_b_display = "\n".join(f"<@{uid}>" for uid in team_b)

        embed = discord.Embed(title="⚔️ 対戦募集", color=discord.Color.blue())
        embed.add_field(name="ステータス", value="```対戦中```", inline=False)
        embed.add_field(name="募集ID", value=f"```{self.unique_id}```", inline=False)
        embed.add_field(name="主催者", value=f"```{organizer_display_name}```", inline=True)
        embed.add_field(name="ホスト", value=f"```{host_display_name}```", inline=True)
        embed.add_field(name="ホストゲームID", value=f"```{game_id}```", inline=True)
        embed.add_field(name="チームA", value=team_a_display, inline=True)
        embed.add_field(name="チームB", value=team_b_display, inline=True)

        await interaction.message.edit(
            embed=embed,
            view=ResultView(self.author_id, self.unique_id, self.participants, host_id, game_id, team_a, team_b)
        )

    @discord.ui.button(label="募集削除", style=discord.ButtonStyle.secondary, custom_id="delete")
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.author_id:
            await interaction.followup.send("この操作は募集主のみが可能です。", ephemeral=True)
            return
        await interaction.message.delete()
        recruitments.pop(interaction.channel_id, None)

class ResultModal(discord.ui.Modal, title="結果入力"):
    def __init__(self, unique_id, user_id, result_view):
        super().__init__()
        self.unique_id = unique_id
        self.user_id = user_id
        self.result_view = result_view

    result = discord.ui.TextInput(label="勝ち or 負け", placeholder="勝ち または 負け", required=True)
    score = discord.ui.TextInput(label="評点 (3.0 - 30.0)", placeholder="例: 25.5", required=True)
    rank = discord.ui.TextInput(label="順位 (1 - 10)", placeholder="例: 3", required=True)
    comment = discord.ui.TextInput(label="コメント", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.result.value not in ["勝ち", "負け"]:
            await interaction.followup.send("勝ち または 負け を入力してください。", ephemeral=True)
            return
        try:
            score = float(self.score.value)
            if not (3.0 <= score <= 30.0): raise ValueError
        except ValueError:
            await interaction.followup.send("評点は3.0から30.0の間の数字で入力してください。", ephemeral=True)
            return
        try:
            rank = int(self.rank.value)
            if self.result.value == "勝ち" and not (1 <= rank <= 5): raise ValueError
            if self.result.value == "負け" and not (6 <= rank <= 10): raise ValueError
        except ValueError:
            await interaction.followup.send("順位が不正です。", ephemeral=True)
            return

        worksheet = await sh.worksheet("result")
        await worksheet.append_row([
            self.unique_id,
            str(self.user_id),
            self.result.value,
            str(score),
            str(rank),
            self.comment.value
        ])

        self.result_view.reported.append(self.user_id)
        await interaction.message.edit(embed=self.result_view.build_embed(), view=self.result_view)

class ResultView(discord.ui.View):
    def __init__(self, author_id, unique_id, participants, host_id, game_id, team_a, team_b):
        super().__init__(timeout=None)
        self.author_id = author_id
        self.unique_id = unique_id
        self.participants = participants
        self.reported = []
        self.host_id = host_id
        self.game_id = game_id
        self.team_a = team_a
        self.team_b = team_b

    def build_embed(self):
        guild = bot.get_guild(next(iter(bot.guilds)).id)

        organizer_member = guild.get_member(self.author_id)
        organizer_display_name = organizer_member.display_name if organizer_member else f"<@{self.author_id}>"

        host_member = guild.get_member(self.host_id)
        host_display_name = host_member.display_name if host_member else f"<@{self.host_id}>"

        embed = discord.Embed(title="⚔️ 対戦募集", color=discord.Color.blue())
        embed.add_field(name="ステータス", value="```対戦中```", inline=False)
        embed.add_field(name="募集ID", value=f"```{self.unique_id}```", inline=False)
        embed.add_field(name="主催者", value=f"```{organizer_display_name}```", inline=True)
        embed.add_field(name="ホスト", value=f"```{host_display_name}```", inline=True)
        embed.add_field(name="ホストゲームID", value=f"```{self.game_id}```", inline=True)

        # チームA
        team_a_display = []
        for uid in self.team_a:
            prefix = "`結果入力済` " if uid in self.reported else ""
            team_a_display.append(f"{prefix}<@{uid}>")
        embed.add_field(name="チームA", value="\n".join(team_a_display), inline=True)

        # チームB
        team_b_display = []
        for uid in self.team_b:
            prefix = "`結果入力済` " if uid in self.reported else ""
            team_b_display.append(f"{prefix}<@{uid}>")
        embed.add_field(name="チームB", value="\n".join(team_b_display), inline=True)

        return embed

    @discord.ui.button(label="結果入力", style=discord.ButtonStyle.primary, custom_id="report")
    async def report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message("参加者のみが結果を報告できます。", ephemeral=True)
            return
        if interaction.user.id in self.reported:
            await interaction.response.send_message("既に結果を報告しています。", ephemeral=True)
            return
        modal = ResultModal(self.unique_id, interaction.user.id, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="入力完了", style=discord.ButtonStyle.success, custom_id="complete")
    async def complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.author_id:
            await interaction.followup.send("この操作は募集主のみが可能です。", ephemeral=True)
            return
        if len(self.reported) < len(self.participants):
            await interaction.followup.send("全員が結果を報告していません。", ephemeral=True)
            return
        embed = discord.Embed(title="⚔️ 対戦募集")
        embed.add_field(name="ステータス", value=f"```対戦終了```", inline=False)
        embed.add_field(name="募集ID", value=f"```{self.unique_id}```", inline=False)
        await interaction.message.edit(embed=embed, view=None)

        worksheet = await sh.worksheet("result")
        all_rows = await worksheet.get_all_values()
        rows = [row for row in all_rows[1:] if row[0] == self.unique_id]
        rows.sort(key=lambda x: int(x[4]))

        lines = []
        for row in rows:
            user_id = int(row[1])
            name = f"<@{user_id}>"
            if user_id == self.author_id:
                name += "🚩"
            result = row[2]
            score = row[3]
            rank = row[4]
            comment = row[5] if len(row) > 5 and row[5] else "なし"
            lines.append(f"{name}｜順位: {rank}｜結果: {result}｜評点: {score}｜備考: {comment}")

        result_embed = discord.Embed(
            title="🏆 対戦結果 🏆",
            description=f"募集ID: {self.unique_id}\n\n" + "\n".join(lines),
            color=discord.Color.gold()
        )

        channel = bot.get_channel(result_announcement_channel_id)
        if channel:
            await channel.send(embed=result_embed)

        recruitments.pop(interaction.channel_id, None)

        await interaction.followup.send("対戦を終了しました。結果を投稿しました。", ephemeral=True)

@tree.command(name="c", description="ゲームの募集を開始します。")
async def c_command(interaction: discord.Interaction):
    if interaction.channel_id not in allowed_channels:
        await interaction.response.send_message("このチャンネルでは募集を開始できません。", ephemeral=True)
        return
    if interaction.channel_id in recruitments:
        await interaction.response.send_message("このチャンネルでは既に募集が開始されています。", ephemeral=True)
        return

    await interaction.response.defer()

    unique_id = generate_unique_id()
    view = RecruitmentView(interaction.user.id, unique_id)

    recruiter_id = interaction.user.id
    recruiter_name = interaction.user.display_name

    embed = discord.Embed(title="⚔️ 対戦募集", color=discord.Color.green())
    embed.add_field(name="ステータス", value=f"```募集中```", inline=False)
    embed.add_field(name="募集ID", value=f"```{unique_id}```", inline=False)
    embed.add_field(name="主催者", value=f"```{recruiter_name}```", inline=True)
    embed.add_field(name="ホスト", value="``` ```", inline=True)
    embed.add_field(name="ホストゲームID", value="``` ```", inline=True)
    embed.add_field(name=f"参加者 1/10", value=f"<@{recruiter_id}>", inline=True)

    await interaction.followup.send(embed=embed, view=view)
    recruitments[interaction.channel_id] = unique_id

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Bot起動: {bot.user} (ID: {bot.user.id})")

    global agc, sh
    agc = await agcm.authorize()
    sh = await agc.open("DiscordBot")

    channel = bot.get_channel(target_channel_id)
    if channel is None:
        print("チャンネルが見つかりません。")
        return

    try:
        async for msg in channel.history(limit=50):
            if msg.author == bot.user and msg.embeds:
                embed = msg.embeds[0]
                if embed.title == EMBED_TITLE:
                    return
    except Exception as e:
        print("履歴取得中にエラー:", e)

    embed = discord.Embed(
        title=EMBED_TITLE,
        description="登録・更新したい方は下のボタンを押してください！",
        color=discord.Color.blurple(),
    )
    await channel.send(embed=embed, view=GameIDView())

@bot.event
async def setup_hook():
    bot.add_view(GameIDView())

TOKEN = "MTM3NTY5MTk0Nzg0NjY2NDI2Mg.Gi1Ax6.A_0E1cNp2zR-NdnT0mup90Km7vw4KEyN4u2e5A"

bot.run(TOKEN)
