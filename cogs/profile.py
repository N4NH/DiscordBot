from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

import database
from helpers import format_star_rating, get_reviewer_rank, get_reviewer_vibe

class ProfileCog(commands.Cog, name="Profile"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="profile", description="Xem hồ sơ và thành tích đánh giá phim của một người dùng trong server")
    @app_commands.guild_only()
    @app_commands.describe(thanh_vien="Chọn người dùng muốn xem (để trống nếu muốn xem của chính bạn)")
    async def cmd_profile(self, interaction: discord.Interaction, thanh_vien: Optional[discord.Member] = None):
        target = thanh_vien or interaction.user
        stats = database.get_user_profile(guild_id=interaction.guild_id, user_id=target.id)

        total_rated = stats["total_rated"]
        avg_score = stats["avg_given_score"]
        rank_title = get_reviewer_rank(total_rated)
        vibe = get_reviewer_vibe(avg_score, total_rated)

        embed = discord.Embed(
            title=f"🎬 Hồ Sơ Phê Bình: {target.display_name}",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        server_rank_text = f"**#{stats['server_rank']}** / {stats['total_reviewers']} người" if stats['server_rank'] else "*Chưa xếp hạng*"

        desc_lines = [
            f"🎖️ **Danh hiệu :** {rank_title}",
            f"🏆 **Xếp hạng server :** {server_rank_text}",
            f"🎬 **Số phim đã chấm :** `{total_rated}` bộ phim",
            f"⭐ **Điểm TB đã chấm :** {format_star_rating(avg_score) if total_rated > 0 else '*Chưa chấm phim nào*'}",
            f"🎭 **Gu thẩm phim :** {vibe}",
        ]

        if stats["highest_movie"]:
            desc_lines.append(f"❤️ **Phim thích nhất :** {stats['highest_movie']['name']} (`{stats['highest_movie']['score']} ⭐`)")

        if stats["lowest_movie"]:
            desc_lines.append(f"💔 **Phim chán nhất :** {stats['lowest_movie']['name']} (`{stats['lowest_movie']['score']} ⭐`)")

        embed.description = "\n".join(desc_lines)

        if stats["recent_reviews"]:
            recent_text = "\n".join([f"• **{r['name']}** — `{r['score']} ⭐`" for r in stats["recent_reviews"]])
            embed.add_field(name="🕒 Đánh giá gần đây trong server", value=recent_text, inline=False)

        embed.set_footer(text="Dùng /rate để chấm điểm phim và thăng hạng danh hiệu!")
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(ProfileCog(bot))
