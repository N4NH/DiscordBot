import io
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands

import database
from helpers import (
    format_star_rating,
    movie_autocomplete,
    create_showcase_embed,
    MovieShowcaseView,
    update_showcase_message,
    process_and_compress_image,
    save_poster_file,
    load_poster_bytes
)

class MoviesCog(commands.Cog, name="Movies"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="kenhchitiet", description="Thiết lập kênh riêng để hiển thị và tự động cập nhật bài đăng phim")
    @app_commands.guild_only()
    @app_commands.describe(kenh="Chọn kênh chat bạn muốn làm nơi giới thiệu phim (để trống để xem kênh hiện tại)")
    async def cmd_kenh_chi_tiet_channel(
        self,
        interaction: discord.Interaction,
        kenh: Optional[discord.TextChannel] = None
    ):
        current_channel_id = database.get_showcase_channel(interaction.guild_id)

        # Nếu không truyền kênh -> Xem kênh hiện tại
        if not kenh:
            if current_channel_id:
                await interaction.response.send_message(
                    f"📌 Kênh hiển thị phim hiện tại của server là: <#{current_channel_id}>.\n"
                    f"👉 Để đổi sang kênh khác, gõ: `/kenhchitiet #tên-kênh`",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "📭 Server này chưa cài đặt kênh hiển thị phim riêng.\n"
                    "👉 Bạn hãy gõ: `/kenhchitiet #tên-kênh` để chọn kênh nhé!",
                    ephemeral=True
                )
            return

        # Kiểm tra quyền quản lý server
        if not interaction.user.guild_permissions.manage_guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Bạn cần có quyền **Quản lý Server** hoặc **Quản trị viên** để thiết lập kênh này!",
                ephemeral=True
            )
            return

        # Lưu vào database
        database.set_showcase_channel(guild_id=interaction.guild_id, channel_id=kenh.id)

        embed = discord.Embed(
            title="🎬 Kênh Chi Tiết Phim Đã Được Thiết Lập!",
            description=(
                f"Kênh {kenh.mention} đã được chọn làm **Kênh Giới Thiệu & Cập Nhật Phim** của server.\n\n"
                f"✨ **Tính năng tự động:**\n"
                f"• Mỗi khi có phim mới được thêm (`/addphim`), bài đăng poster sẽ được gửi vào {kenh.mention}.\n"
                f"• Mỗi khi có ai vote sao (`/rate`), bài đăng trong {kenh.mention} sẽ **tự động cập nhật điểm số theo thời gian thực**.\n"
                f"• Ổn định vĩnh viễn, không lo lỗi tin nhắn cũ!"
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="addphim", description="Thêm phim mới vào danh sách đánh giá của server")
    @app_commands.guild_only()
    @app_commands.describe(
        ten_phim="Tên bộ phim bạn muốn thêm",
        anh="Đính kèm file ảnh poster từ máy tính hoặc điện thoại",
        link_anh="Hoặc dán URL link ảnh poster trực tuyến"
    )
    async def cmd_add_phim(
        self,
        interaction: discord.Interaction,
        ten_phim: str,
        anh: Optional[discord.Attachment] = None,
        link_anh: Optional[str] = None
    ):
        if not anh and not link_anh:
            await interaction.response.send_message(
                "❌ Vui lòng đính kèm một file ảnh (`anh`) hoặc điền link ảnh trực tuyến (`link_anh`) làm poster cho phim!",
                ephemeral=True
            )
            return

        # Defer trước để tránh Discord timeout khi nén ảnh
        await interaction.response.defer()

        compressed_data, fallback_url = await process_and_compress_image(attachment=anh, url=link_anh)
        if not compressed_data and not fallback_url:
            await interaction.followup.send("❌ Không thể xử lý ảnh poster! Vui lòng thử lại.", ephemeral=True)
            return

        success, msg, movie_id = database.add_movie(
            guild_id=interaction.guild_id,
            name=ten_phim,
            image_url=fallback_url or "",
            created_by=f"{interaction.user.name}",
            image_data=compressed_data
        )

        if not success or not movie_id:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            return

        # Lưu ảnh vào thư mục posters/ trên máy tính
        if compressed_data:
            save_poster_file(movie_id, ten_phim, compressed_data)

        # Kiểm tra xem server có cài kênh chi tiết phim không
        showcase_channel_id = database.get_showcase_channel(interaction.guild_id)
        showcase_notice = ""

        if showcase_channel_id:
            try:
                ch = self.bot.get_channel(showcase_channel_id) or await self.bot.fetch_channel(showcase_channel_id)
                if ch:
                    showcase_embed = create_showcase_embed({
                        "name": ten_phim,
                        "image_url": fallback_url or "",
                        "image_data": compressed_data,
                        "created_by": interaction.user.name,
                        "avg_score": 0.0,
                        "total_votes": 0
                    })
                    post_file = discord.File(io.BytesIO(compressed_data), filename="poster.jpg") if compressed_data else None
                    if post_file:
                        post_msg = await ch.send(embed=showcase_embed, file=post_file, view=MovieShowcaseView())
                    else:
                        post_msg = await ch.send(embed=showcase_embed, view=MovieShowcaseView())
                    database.set_movie_showcase_message_id(movie_id, post_msg.id)
                    showcase_notice = f"\n\n📢 *Đã tự động đăng bài giới thiệu vào kênh {ch.mention}!*"
            except Exception as e:
                print(f"Lỗi khi gửi bài đăng vào kênh chi tiết: {e}")

        embed = discord.Embed(
            title="🎬 Thêm Phim Thành Công!",
            description=(
                f"Bộ phim **{ten_phim}** đã được thêm vào hệ thống đánh giá của server.\n\n"
                f"👤 **Người thêm :** {interaction.user.mention}\n"
                f"⭐ **Điểm số :** Chưa có đánh giá *(Dùng `/rate` để chấm sao)*\n"
                f"📁 **Lưu trữ :** Đã lưu ảnh vào thư mục `posters/` trên máy tính"
                f"{showcase_notice}"
            ),
            color=discord.Color.green()
        )
        resp_file = None
        if compressed_data:
            resp_file = discord.File(io.BytesIO(compressed_data), filename="poster.jpg")
            embed.set_image(url="attachment://poster.jpg")
        elif fallback_url:
            embed.set_image(url=fallback_url)

        embed.set_footer(text="Gõ /rate để bắt đầu chấm điểm cho phim này!")

        if resp_file:
            await interaction.followup.send(embed=embed, file=resp_file)
        else:
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="chitiet", description="Xem thông tin chi tiết và poster của một bộ phim trong server")
    @app_commands.guild_only()
    @app_commands.describe(ten_phim="Nhập tên phim cần xem")
    @app_commands.autocomplete(ten_phim=movie_autocomplete)
    async def cmd_chi_tiet(self, interaction: discord.Interaction, ten_phim: str):
        movie = database.get_movie(guild_id=interaction.guild_id, name=ten_phim)
        if not movie:
            await interaction.response.send_message(
                f"❌ Không tìm thấy phim **'{ten_phim}'** trong server này!",
                ephemeral=True
            )
            return

        user_score = database.get_user_rating(guild_id=interaction.guild_id, movie_name=ten_phim, user_id=interaction.user.id)
        user_status = f"**{user_score} ⭐**" if user_score is not None else "*Bạn chưa đánh giá phim này*"

        embed = discord.Embed(
            title=f"🎬 Thông Tin Phim: {movie['name']}",
            description=(
                f"⭐ **Điểm trung bình :** {format_star_rating(movie['avg_score'])}\n"
                f"👥 **Tổng lượt đánh giá :** `{movie['total_votes']}` lượt\n"
                f"🙋 **Điểm của bạn :** {user_status}\n"
                f"👤 **Người thêm :** `{movie.get('created_by', 'Không rõ')}`"
            ),
            color=discord.Color.dark_teal()
        )
        img_bytes = load_poster_bytes(movie)
        file = None
        if img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename="poster.jpg")
            embed.set_image(url="attachment://poster.jpg")
        elif movie.get("image_url"):
            embed.set_image(url=movie["image_url"])

        embed.set_footer(text="Dùng lệnh /rate để chấm điểm cho phim này!")
        if file:
            await interaction.response.send_message(embed=embed, file=file)
        else:
            await interaction.response.send_message(embed=embed)

    @app_commands.command(name="suaphim", description="Chỉnh sửa tên hoặc ảnh poster của một bộ phim trong server")
    @app_commands.guild_only()
    @app_commands.describe(
        ten_goc="Chọn hoặc nhập tên bộ phim hiện tại cần sửa",
        ten_moi="Nhập tên mới muốn đổi thành (để trống nếu chỉ đổi ảnh)",
        anh="Đính kèm file ảnh poster mới từ thiết bị",
        link_anh="Hoặc dán URL link ảnh poster mới trực tuyến"
    )
    @app_commands.autocomplete(ten_goc=movie_autocomplete)
    async def cmd_sua_phim(
        self,
        interaction: discord.Interaction,
        ten_goc: str,
        ten_moi: Optional[str] = None,
        anh: Optional[discord.Attachment] = None,
        link_anh: Optional[str] = None
    ):
        if not ten_moi and not anh and not link_anh:
            await interaction.response.send_message(
                "❌ Vui lòng nhập tên mới (`ten_moi`) hoặc cung cấp ảnh poster mới (`anh` / `link_anh`) để cập nhật phim!",
                ephemeral=True
            )
            return

        # Defer trước để tránh Discord timeout khi nén ảnh
        await interaction.response.defer()

        compressed_data = None
        fallback_url = None
        if anh or link_anh:
            compressed_data, fallback_url = await process_and_compress_image(attachment=anh, url=link_anh)

        success, msg, updated_movie = database.update_movie(
            guild_id=interaction.guild_id,
            old_name=ten_goc,
            new_name=ten_moi,
            new_image_url=fallback_url,
            new_image_data=compressed_data
        )
        if success and updated_movie:
            # Lưu file ảnh mới hoặc đổi tên file ảnh nếu đổi tên phim
            if compressed_data:
                save_poster_file(updated_movie["id"], updated_movie["name"], compressed_data)
            elif ten_moi and ten_moi.strip() != ten_goc.strip():
                existing_bytes = load_poster_bytes(updated_movie)
                if existing_bytes:
                    save_poster_file(updated_movie["id"], updated_movie["name"], existing_bytes)

            # Tự động cập nhật bài đăng trong kênh chi tiết phim nếu có
            await update_showcase_message(self.bot, interaction.guild_id, updated_movie, new_image=bool(compressed_data or fallback_url))

            changes = []
            if ten_moi and ten_moi.strip().lower() != ten_goc.strip().lower():
                changes.append(f"🎬 **Tên gốc :** `{ten_goc}`\n✨ **Tên mới :** **{updated_movie['name']}**")
            elif ten_moi and ten_moi.strip() != ten_goc.strip():
                changes.append(f"✨ **Tên mới :** **{updated_movie['name']}**")
            else:
                changes.append(f"🎬 **Phim :** **{updated_movie['name']}**")

            if compressed_data or fallback_url:
                changes.append("🖼️ **Poster :** Đã cập nhật ảnh poster mới vào thư mục `posters/`")

            changes_desc = "\n".join(changes)

            embed = discord.Embed(
                title="✏️ Cập Nhật Phim Thành Công!",
                description=(
                    f"{changes_desc}\n\n"
                    f"⭐ Điểm số và toàn bộ lượt đánh giá cũ vẫn được bảo lưu nguyên vẹn."
                ),
                color=discord.Color.green()
            )
            img_bytes = load_poster_bytes(updated_movie)
            file = None
            if img_bytes:
                file = discord.File(io.BytesIO(img_bytes), filename="poster.jpg")
                embed.set_image(url="attachment://poster.jpg")
            elif updated_movie.get("image_url"):
                embed.set_image(url=updated_movie["image_url"])

            if file:
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)

    @app_commands.command(name="xoaphim", description="Xóa một bộ phim khỏi danh sách của server")
    @app_commands.guild_only()
    @app_commands.describe(ten_phim="Nhập tên phim cần xóa")
    @app_commands.autocomplete(ten_phim=movie_autocomplete)
    async def cmd_xoa_phim(self, interaction: discord.Interaction, ten_phim: str):
        success, msg, showcase_msg_id = database.delete_movie(guild_id=interaction.guild_id, name=ten_phim)
        if success:
            # Tự động dọn dẹp bài đăng trong kênh chi tiết phim nếu có
            showcase_channel_id = database.get_showcase_channel(interaction.guild_id)
            if showcase_channel_id and showcase_msg_id:
                try:
                    ch = self.bot.get_channel(showcase_channel_id) or await self.bot.fetch_channel(showcase_channel_id)
                    if ch:
                        m = await ch.fetch_message(showcase_msg_id)
                        await m.delete()
                except Exception:
                    pass
            await interaction.response.send_message(f"🗑️ {msg}")
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MoviesCog(bot))
