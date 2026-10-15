from typing import List, Dict, Optional, Union
import discord
from discord import app_commands
from discord.ext import commands

COMMANDS_LIST: List[Dict[str, str]] = [
    {
        "name": "➕ `/addphim <tên_phim> [ảnh] [link_ảnh]`",
        "value": "Thêm phim vào server. Có thể đính kèm file ảnh poster hoặc dán link ảnh trực tuyến."
    },
    {
        "name": "⭐ `/rate <tên_phim>`",
        "value": "Chấm điểm sao cho phim từ **1.0 đến 5.0 sao** (hỗ trợ số lẻ 3.5, 4.5). Có gợi ý tên phim của server khi gõ."
    },
    {
        "name": "🏆 `/bxh [loại] [giới_hạn]`",
        "value": "Xem bảng xếp hạng **Phim hay nhất** hoặc **Top người đánh giá** trong server."
    },
    {
        "name": "✏️ `/suaphim <tên_gốc> [tên_mới] [ảnh] [link_anh]`",
        "value": "Chỉnh sửa đổi tên hoặc ảnh poster của phim trong server (toàn bộ điểm và vote cũ được giữ nguyên)."
    },
    {
        "name": "👥 `/topreviewer [giới_hạn]`",
        "value": "Xem nhanh bảng xếp hạng các nhà phê bình tích cực nhất server."
    },
    {
        "name": "🔍 `/chitiet <tên_phim>`",
        "value": "Xem thông tin chi tiết phim: poster to, điểm trung bình và điểm bạn đã chấm."
    },
    {
        "name": "👤 `/profile [thành_viên]`",
        "value": "Xem hồ sơ cá nhân trong server: danh hiệu phê bình, số phim đã chấm, điểm TB và gu thẩm phim."
    },
    {
        "name": "🗑️ `/xoaphim <tên_phim>`",
        "value": "Xóa một bộ phim khỏi danh sách của server."
    },
    {
        "name": "📺 `/kenhchitiet [kênh]`",
        "value": "Chỉ định kênh riêng để tự động đăng poster và cập nhật điểm số phim theo thời gian thực."
    },
    {
        "name": "🤬 `/chuibay <thành_viên>`",
        "value": "Tag và chửi ngẫu nhiên một người bằng văn mẫu ."
    },
    {
        "name": "🎰 `/gru <mục 1; mục 2...>`",
        "value": "Quay số may mắn chọn ngẫu nhiên một mục với hiệu ứng quay số (ngăn cách bằng `;` hoặc `'` hoặc `[]`)."
    },
    {
        "name": "🥰 `/rep <thành_viên>`",
        "value": "Phản hồi siêu cute và ngoan ngoãn với một ai đó bằng văn mẫu ngẫu nhiên ."
    },
    {
        "name": "🤖 `/gpt <câu_hỏi>`",
        "value": "Hỏi đáp với trợ lí ảo AI thông minh, tự động tra cứu Google/Internet khi hỏi về người hoặc sự kiện mới "
    },
    {
        "name": "🎵 `/play <tên_bài_hát_hoặc_link> [platform]`",
        "value": "Phát nhạc đa nền tảng (YouTube, SoundCloud, Spotify). Hỗ trợ link bài hát, album, playlist hoặc từ khóa tìm kiếm. Có bàn phím tương tác chuẩn Jockey Music."
    },
    {
        "name": "🟢 `/play_spotify <tên_hoặc_link>`",
        "value": "Tìm kiếm hoặc phát nhạc từ link Spotify (bài lẻ, album, playlist) qua Spotify Bridge thông minh."
    },
    {
        "name": "🟠 `/play_soundcloud <tên_hoặc_link>`",
        "value": "Tìm kiếm và phát nhạc riêng từ nền tảng SoundCloud."
    },
    {
        "name": "🔴 `/play_youtube <tên_hoặc_link>`",
        "value": "Tìm kiếm và phát nhạc riêng từ YouTube."
    },
    {
        "name": "📜 `/queue` | `/nowplaying`",
        "value": "Xem danh sách các bài hát trong hàng chờ hoặc xem bảng điều khiển bài hát đang phát."
    },
    {
        "name": "⏯️ `/pause` | `/resume` | `/skip` | `/stop`",
        "value": "Các thao tác điều khiển phát nhạc nhanh (tạm dừng, tiếp tục, bỏ qua bài, dừng & xóa hàng chờ)."
    },
    {
        "name": "🎚️ `/volume` | `/loop` | `/shuffle`",
        "value": "Tùy chỉnh âm lượng (1-150%), chế độ lặp (Tắt / 1 bài / Toàn bộ queue), hoặc trộn ngẫu nhiên hàng chờ."
    },
    {
        "name": "⏰ `/remind <giờ:phút:giây> <ghi_chú>`",
        "value": "Đặt lịch hẹn giờ nhắc việc (nhập hours:minutes:seconds). Khi đến giờ bot sẽ tự động tag bạn vào kênh để nhắc việc."
    },
    {
        "name": "📋 `/remind_list` | `/remind_cancel <id>`",
        "value": "Xem danh sách các lời nhắc đang chờ chuông hoặc hủy một lời nhắc cụ thể theo mã ID."
    },
]


class HelpPaginationView(discord.ui.View):
    def __init__(
        self,
        author: Union[discord.User, discord.Member],
        commands_list: List[Dict[str, str]],
        bot_name: str = "Bánh Gấu",
        per_page: int = 5
    ):
        super().__init__(timeout=120)
        self.author = author
        self.commands_list = commands_list
        self.bot_name = bot_name
        self.per_page = per_page
        self.total_pages = max(1, (len(commands_list) + per_page - 1) // per_page)
        self.current_page = 0
        self.message: Optional[discord.Message] = None
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.page_indicator.label = f"{self.current_page + 1}/{self.total_pages}"
        self.next_btn.disabled = (self.current_page >= self.total_pages - 1)

    def get_embed(self) -> discord.Embed:
        start_idx = self.current_page * self.per_page
        end_idx = start_idx + self.per_page
        page_commands = self.commands_list[start_idx:end_idx]

        embed = discord.Embed(
            title=f"📖 Hướng Dẫn Sử Dụng {self.bot_name}  ⸜(｡˃ ᵕ ˂ )⸝♡",
            description=(
                f"Chào mừng bạn đến với hệ thống bot của server!\n"
                f"**{self.bot_name}** sẽ giúp đỡ các bạn trong việc lưu trữ lại những bộ phim đã xem cùng nhau >.<\n\n"
                f"Dưới đây là các lệnh:\n"
                f"{'─' * 40}"
            ),
            color=discord.Color.blurple()
        )

        for cmd in page_commands:
            embed.add_field(
                name=cmd["name"],
                value=cmd["value"],
                inline=False
            )

        embed.set_footer(
            text=f"Trang {self.current_page + 1}/{self.total_pages} • Sử dụng nút ⬅️ và ➡️ để chuyển trang"
        )
        return embed

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary, custom_id="help_prev")
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Chỉ người dùng lệnh mới có thể chuyển trang!", ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="help_page_num")
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Nút hiển thị số trang hiện tại
        pass

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary, custom_id="help_next")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Chỉ người dùng lệnh mới có thể chuyển trang!", ephemeral=True)
            return

        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.get_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass


class HelpCog(commands.Cog, name="Help"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Xem hướng dẫn sử dụng các lệnh của Bot")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def cmd_help(self, interaction: discord.Interaction):
        # Lấy biệt danh của bot được đặt trong server (nếu không có thì lấy tên mặc định)
        bot_member = interaction.guild.me if interaction.guild else None
        bot_name = (
            bot_member.display_name
            if bot_member
            else (self.bot.user.display_name if self.bot.user else "Bánh Gấu")
        )

        view = HelpPaginationView(
            author=interaction.user,
            commands_list=COMMANDS_LIST,
            bot_name=bot_name,
            per_page=5
        )
        await interaction.response.send_message(embed=view.get_embed(), view=view)
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot))
