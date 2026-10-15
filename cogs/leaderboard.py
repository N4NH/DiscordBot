import io
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

import database
from helpers import get_reviewer_rank, load_poster_bytes

class LeaderboardCog(commands.Cog, name="Leaderboard"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def show_movie_leaderboard(self, interaction: discord.Interaction, limit: int):
        """Hiển thị bảng xếp hạng phim hay nhất trong server hiện tại"""
        leaderboard = database.get_leaderboard(guild_id=interaction.guild_id, limit=limit)
        if not leaderboard:
            await interaction.response.send_message(
                "📭 Server này chưa có bộ phim nào trong danh sách. Hãy dùng `/addphim` để thêm phim đầu tiên nhé!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 BẢNG XẾP HẠNG PHIM HAY NHẤT",
            description="Danh sách các bộ phim được chúng tui yêu thích và đánh giá cao nhất٩(ˊᗜˋ*)و :\n" + "─" * 40,
            color=discord.Color.gold()
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, movie in enumerate(leaderboard, start=1):
            icon = medals[idx - 1] if idx <= 3 else f"`#{idx:02d}`"
            score_display = f"⭐ **{movie['avg_score']:.1f}**/5.0" if movie["total_votes"] > 0 else "*Chưa có vote*"
            lines.append(
                f"{icon} **{movie['name']}**\n"
                f"└ {score_display} • `{movie['total_votes']} đánh giá`\n"
            )

        embed.description += "\n" + "\n".join(lines)
        top_file = None
        if leaderboard:
            top_movie = leaderboard[0]
            img_bytes = load_poster_bytes(top_movie)
            if img_bytes:
                top_file = discord.File(io.BytesIO(img_bytes), filename="thumb.jpg")
                embed.set_thumbnail(url="attachment://thumb.jpg")
            elif top_movie.get("image_url"):
                embed.set_thumbnail(url=top_movie["image_url"])

        embed.set_footer(text=f"Dùng /rate để chấm điểm • Tổng số phim server: {len(leaderboard)}")
        if top_file:
            await interaction.response.send_message(embed=embed, file=top_file)
        else:
            await interaction.response.send_message(embed=embed)

    async def show_reviewer_leaderboard(self, interaction: discord.Interaction, limit: int):
        """Hiển thị bảng xếp hạng thành viên review tích cực nhất server hiện tại"""
        reviewers = database.get_top_reviewers(guild_id=interaction.guild_id, limit=limit)
        if not reviewers:
            await interaction.response.send_message(
                "📭 Server này chưa có ai đánh giá phim nào cả! Hãy dùng `/rate` để mở màn nhé!",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 BẢNG XẾP HẠNG NHÀ PHÊ BÌNH PHIM",
            description="Top những thành viên tích cực đánh giá phim nhất server:\n" + "─" * 40,
            color=discord.Color.magenta()
        )

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, r in enumerate(reviewers, start=1):
            icon = medals[idx - 1] if idx <= 3 else f"`#{idx:02d}`"
            rank_badge = get_reviewer_rank(r["total_rated"])
            user_mention = f"<@{r['user_id']}>"
            lines.append(
                f"{icon} {user_mention} — **{r['total_rated']}** phim\n"
                f"└ ⭐ TB: `{r['avg_given_score']:.1f}/5.0` • {rank_badge}\n"
            )

        embed.description += "\n" + "\n".join(lines)
        embed.set_footer(text="Dùng /rate để cày review đua top • Xem chi tiết bằng /profile")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bxh", description="Xem bảng xếp hạng phim hoặc người đánh giá của server")
    @app_commands.guild_only()
    @app_commands.describe(
        loai="Chọn loại bảng xếp hạng muốn xem",
        gioi_han="Số lượng hiển thị (mặc định 10, tối đa 25)"
    )
    @app_commands.choices(loai=[
        app_commands.Choice(name="🎬 Phim hay nhất", value="phim"),
        app_commands.Choice(name="👥 Top người đánh giá", value="nguoi")
    ])
    async def cmd_bxh(
        self,
        interaction: discord.Interaction,
        loai: Optional[app_commands.Choice[str]] = None,
        gioi_han: Optional[int] = 10
    ):
        limit = min(max(gioi_han or 10, 1), 25)
        selected_type = loai.value if loai else "phim"

        if selected_type == "nguoi":
            await self.show_reviewer_leaderboard(interaction, limit)
        else:
            await self.show_movie_leaderboard(interaction, limit)

    @app_commands.command(name="topreviewer", description="Xem bảng xếp hạng những người đánh giá phim tích cực nhất server")
    @app_commands.guild_only()
    @app_commands.describe(gioi_han="Số lượng hiển thị (mặc định 10, tối đa 25)")
    async def cmd_top_reviewer(self, interaction: discord.Interaction, gioi_han: Optional[int] = 10):
        limit = min(max(gioi_han or 10, 1), 25)
        await self.show_reviewer_leaderboard(interaction, limit)

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
