import io
import discord
from discord import app_commands
from discord.ext import commands

import database
from helpers import format_star_rating, movie_autocomplete, update_showcase_message, load_poster_bytes

# View chứa Dropdown Menu để đánh giá sao (1.0 đến 5.0 sao, có cả số lẻ)
class RatingSelect(discord.ui.Select):
    def __init__(self, guild_id: int, movie_name: str):
        self.guild_id = guild_id
        self.movie_name = movie_name
        options = [
            discord.SelectOption(label="⭐⭐⭐⭐⭐ 5.0 Sao", value="5.0", description="Siêu phẩm đỉnh cao / Tuyệt tác!"),
            discord.SelectOption(label="⭐⭐⭐⭐½ 4.5 Sao", value="4.5", description="Rất xuất sắc, đáng xem"),
            discord.SelectOption(label="⭐⭐⭐⭐☆ 4.0 Sao", value="4.0", description="Phim rất hay, nội dung tốt"),
            discord.SelectOption(label="⭐⭐⭐½☆ 3.5 Sao", value="3.5", description="Khá hay, giải trí tốt"),
            discord.SelectOption(label="⭐⭐⭐☆☆ 3.0 Sao", value="3.0", description="Xem ổn, ở mức trung bình"),
            discord.SelectOption(label="⭐⭐½☆☆ 2.5 Sao", value="2.5", description="Bình thường, hơi thiếu điểm nhấn"),
            discord.SelectOption(label="⭐⭐☆☆☆ 2.0 Sao", value="2.0", description="Hơi chán, xem mất thời gian"),
            discord.SelectOption(label="⭐½☆☆☆ 1.5 Sao", value="1.5", description="Tệ, kịch bản lủng củng"),
            discord.SelectOption(label="⭐☆☆☆☆ 1.0 Sao", value="1.0", description="Rất tệ / Thảm họa điện ảnh"),
        ]
        super().__init__(
            placeholder="🎬 Chọn số sao bạn muốn chấm cho phim...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        score = float(self.values[0])
        user = interaction.user
        success, msg, updated, is_update, old_score = database.rate_movie(
            guild_id=self.guild_id,
            movie_name=self.movie_name,
            user_id=user.id,
            user_name=f"{user.name}",
            score=score
        )
        
        if not success or not updated:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            return

        # Tự động cập nhật bài đăng trong kênh chi tiết phim theo thời gian thực
        if hasattr(self.view, "bot") and self.view.bot:
            await update_showcase_message(self.view.bot, interaction.guild_id, updated)

        # Phân biệt rõ ràng giữa đánh giá lần đầu và sửa đánh giá
        if is_update:
            status_desc = (
                f"🔄 **{user.mention}** đã **cập nhật đánh giá**: từ **{old_score} ⭐** ➔ **{score} ⭐**\n"
                f"📌 *Mỗi thành viên chỉ có tối đa 1 đánh giá, tổng lượt vote của phim không đổi.*"
            )
        else:
            status_desc = (
                f"🎉 Cảm ơn **{user.mention}** đã đánh giá lần đầu: **{score} ⭐**!\n"
                f"📌 *Đánh giá của bạn đã được ghi nhận vào hệ thống server.*"
            )

        embed = discord.Embed(
            title=f"🎬 Đánh Giá: {updated['name']}",
            description=(
                f"{status_desc}\n\n"
                f"👤 **Người đánh giá :** {user.mention}\n"
                f"⭐ **Điểm trung bình :** {format_star_rating(updated['avg_score'])}\n"
                f"👥 **Tổng lượt đánh giá :** `{updated['total_votes']}` người"
            ),
            color=discord.Color.teal() if is_update else discord.Color.gold()
        )
        img_bytes = load_poster_bytes(updated)
        if img_bytes:
            embed.set_image(url="attachment://poster.jpg")
        elif updated.get("image_url"):
            embed.set_image(url=updated["image_url"])
        embed.set_footer(text="Mỗi người chỉ có 1 đánh giá. Bạn có thể chọn lại sao bên dưới nếu muốn sửa tiếp.")

        # Cập nhật tin nhắn kèm view
        await interaction.response.edit_message(embed=embed, view=self.view)

class RatingView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, movie_name: str, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.movie_name = movie_name
        self.author_id = author_id
        self.add_item(RatingSelect(guild_id=guild_id, movie_name=movie_name))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Đảm bảo chỉ người gọi lệnh mới tương tác được với menu này
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Menu đánh giá này dành riêng cho người đã gọi lệnh. Vui lòng tự gõ `/rate` để chấm điểm nhé!",
                ephemeral=True
            )
            return False
        return True

class RatingsCog(commands.Cog, name="Ratings"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="rate", description="Đánh giá sao cho một bộ phim (từ 1.0 đến 5.0 sao)")
    @app_commands.guild_only()
    @app_commands.describe(ten_phim="Nhập tên phim cần đánh giá")
    @app_commands.autocomplete(ten_phim=movie_autocomplete)
    async def cmd_rate(self, interaction: discord.Interaction, ten_phim: str):
        movie = database.get_movie(guild_id=interaction.guild_id, name=ten_phim)
        if not movie:
            await interaction.response.send_message(
                f"❌ Không tìm thấy phim **'{ten_phim}'** trong server này! Hãy dùng lệnh `/addphim` để thêm trước.",
                ephemeral=True
            )
            return

        user_prev_score = database.get_user_rating(guild_id=interaction.guild_id, movie_name=ten_phim, user_id=interaction.user.id)
        prev_text = f"**{user_prev_score} ⭐**" if user_prev_score is not None else "*Chưa đánh giá*"

        embed = discord.Embed(
            title=f"🎬 Đánh Giá Phim: {movie['name']}",
            description=(
                f"Hãy chọn số sao bạn muốn chấm ở danh sách bên dưới!\n\n"
                f"⭐ **Điểm hiện tại :** {format_star_rating(movie['avg_score'])}\n"
                f"👥 **Tổng lượt đánh giá :** `{movie['total_votes']}` người\n"
                f"🙋 **Điểm của bạn :** {prev_text}"
            ),
            color=discord.Color.blue()
        )
        img_bytes = load_poster_bytes(movie)
        file = None
        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename="poster.jpg")
            embed.set_image(url="attachment://poster.jpg")
        elif movie.get("image_url"):
            embed.set_image(url=movie["image_url"])
        embed.set_footer(text="Hỗ trợ các mức sao từ 1.0 đến 5.0 (kèm số lẻ 3.5, 4.5, ...)")

        view = RatingView(bot=self.bot, guild_id=interaction.guild_id, movie_name=movie["name"], author_id=interaction.user.id)
        if file:
            await interaction.response.send_message(embed=embed, file=file, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(RatingsCog(bot))
