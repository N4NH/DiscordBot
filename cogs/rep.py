import os
import random
import re
from typing import List
import discord
from discord import app_commands
from discord.ext import commands

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAN_MAU_REP_FILE = os.path.join(ROOT_DIR, "van_mau_rep.txt")

DEFAULT_REP_TEMPLATES = [
    "Dạ oki [@] lùn ( ˶ˆ꒳ˆ˵ )",
    "Vâng ạ [@], em nghe nè ~ có gì dặn dò em hông? (人 •͈ᴗ•͈)",
    "Dạ tuân lệnh sếp [@], em làm liền ạ! (｡•̀ᴗ-)✧",
    "Oki [@], yêu yêu nè moazzz ( ˘ ³˘)♥",
    "Em có mặt rồi nè [@], nhớ em hông nè? (◕‿◕✿)",
    "Dạ em nghe sếp [@] dặn rồi ạ, sếp ngoan ghê á! ( ˆ͈̑꒳ˆ͈̑ )",
    "Dạ vâng [@], chuyện nhỏ để em lo nhen! (づ｡◕‿‿◕｡)づ",
    "Dạ oki [@], ngoan ngoãn nghe lời sếp nè! ( ⁎ᵕᴗᵕ⁎ )",
]


def load_van_mau_rep() -> List[str]:
    """Đọc toàn bộ văn mẫu cute từ file van_mau_rep.txt."""
    if not os.path.exists(VAN_MAU_REP_FILE):
        return DEFAULT_REP_TEMPLATES.copy()

    try:
        with open(VAN_MAU_REP_FILE, "r", encoding="utf-8") as f:
            lines = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
        return lines if lines else DEFAULT_REP_TEMPLATES.copy()
    except Exception:
        return DEFAULT_REP_TEMPLATES.copy()


def format_rep_sentence(template: str, mention: str) -> str:
    """Thay thế placeholder như [@], @[], {target}, v.v. bằng mention."""
    placeholders = [
        r"\[@\]",
        r"@\[\]",
        r"\[@nguoi bị tag\]",
        r"\[@người bị tag\]",
        r"\[@nguoi bi tag\]",
        r"\{target\}",
        r"\{user\}",
        r"\{tag\}",
    ]

    result = template
    replaced = False

    for ph in placeholders:
        pattern = re.compile(ph, re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(mention, result)
            replaced = True

    # Nếu câu không chứa placeholder nào, tự động gắn tag vào đầu câu
    if not replaced:
        result = f"{mention} {result}"

    return result


class RepCog(commands.Cog, name="Rep"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="rep",
        description="Phản hồi siêu cute và ngoan ngoãn với một ai đó bằng văn mẫu ngẫu nhiên (dùng được cả trong DM)"
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(thanh_vien="Chọn người mà bạn muốn phản hồi cute")
    async def cmd_rep(self, interaction: discord.Interaction, thanh_vien: discord.User):
        if thanh_vien.id == self.bot.user.id:
            await interaction.response.send_message(
                f"Dạ {interaction.user.mention} gọi em có chuyện gì hông nè? Em nghe nè moazzz ( ˶ˆ꒳ˆ˵ )~",
                allowed_mentions=discord.AllowedMentions(users=True)
            )
            return

        templates = load_van_mau_rep()
        chosen = random.choice(templates)
        content = format_rep_sentence(chosen, thanh_vien.mention)

        await interaction.response.send_message(
            content,
            allowed_mentions=discord.AllowedMentions(users=True)
        )

    # Hỗ trợ cả lệnh chat thường !rep @user
    @commands.command(name="rep")
    async def prefix_rep(self, ctx: commands.Context, thanh_vien: discord.User):
        if thanh_vien.id == self.bot.user.id:
            await ctx.send(
                f"Dạ {ctx.author.mention} gọi em có chuyện gì hông nè? Em nghe nè moazzz ( ˶ˆ꒳ˆ˵ )~",
                allowed_mentions=discord.AllowedMentions(users=True)
            )
            return

        templates = load_van_mau_rep()
        chosen = random.choice(templates)
        content = format_rep_sentence(chosen, thanh_vien.mention)

        await ctx.send(
            content,
            allowed_mentions=discord.AllowedMentions(users=True)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(RepCog(bot))
