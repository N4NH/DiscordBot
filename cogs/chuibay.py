import os
import random
import re
from typing import List
import discord
from discord import app_commands
from discord.ext import commands

# Đường dẫn tới file van_mau.txt ở thư mục gốc của bot
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAN_MAU_FILE = os.path.join(ROOT_DIR, "van_mau.txt")

DEFAULT_TEMPLATES = [
    "địt mẹ thằng [@] nhìn cái mặt là thấy ghét rồi đấy!",
]

def load_van_mau() -> List[str]:
    """Đọc toàn bộ văn mẫu từ file van_mau.txt."""
    if not os.path.exists(VAN_MAU_FILE):
        try:
            with open(VAN_MAU_FILE, "w", encoding="utf-8") as f:
                f.write("# Mỗi dòng là 1 câu văn mẫu. Dùng [@] để thay thế người bị chửi.\n")
                f.write("\n".join(DEFAULT_TEMPLATES) + "\n")
        except Exception:
            pass
        return DEFAULT_TEMPLATES.copy()

    try:
        with open(VAN_MAU_FILE, "r", encoding="utf-8") as f:
            lines = [
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            ]
        return lines if lines else DEFAULT_TEMPLATES.copy()
    except Exception:
        return DEFAULT_TEMPLATES.copy()

def format_sentence(template: str, mention: str) -> str:
    """Thay thế placeholder như [@], [@nguoi bị tag], {target}, v.v. bằng mention."""
    placeholders = [
        r"\[@\]",
        r"\[@nguoi bị tag\]",
        r"\[@người bị tag\]",
        r"\[@nguoi bi tag\]",
        r"\{target\}",
        r"\{user\}",
        r"\{tag\}",
        r"\{nguoi_bi_tag\}",
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


class ChuiBayCog(commands.Cog, name="ChuiBay"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="chuibay", description="Tag và chửi một người bằng văn mẫu ngẫu nhiên (dùng được cả trong DM)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(thanh_vien="Chọn người mà bạn muốn chửi")
    async def cmd_chuibay(self, interaction: discord.Interaction, thanh_vien: discord.User):
        # Tránh trường hợp người dùng chửi chính bot
        if thanh_vien.id == self.bot.user.id:
            await interaction.response.send_message(
                f"Định chửi tao hả {interaction.user.mention}? Đánh chết bà mày giờ!",
                allowed_mentions=discord.AllowedMentions(users=True)
            )
            return

        templates = load_van_mau()
        chosen_template = random.choice(templates)
        content = format_sentence(chosen_template, thanh_vien.mention)

        await interaction.response.send_message(
            content,
            allowed_mentions=discord.AllowedMentions(users=True)
        )

    # Lệnh chat thường bằng prefix !chuibay @user
    @commands.command(name="chuibay")
    async def prefix_chuibay(self, ctx: commands.Context, thanh_vien: discord.User):
        if thanh_vien.id == self.bot.user.id:
            await ctx.send(
                f"Định chửi tao hả {ctx.author.mention}? Đánh chết bà mày giờ!",
                allowed_mentions=discord.AllowedMentions(users=True)
            )
            return

        templates = load_van_mau()
        chosen_template = random.choice(templates)
        content = format_sentence(chosen_template, thanh_vien.mention)

        await ctx.send(
            content,
            allowed_mentions=discord.AllowedMentions(users=True)
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ChuiBayCog(bot))
