import asyncio
import random
import re
from typing import List
import discord
from discord import app_commands
from discord.ext import commands


def parse_choices(raw_text: str) -> List[str]:
    """Tách các lựa chọn từ chuỗi đầu vào theo dấu ; hoặc ' hoặc [ ] hoặc ,"""
    # 1. Kiểm tra dấu chấm phẩy ;
    if ";" in raw_text:
        parts = [p.strip().strip("[]'\"").strip() for p in raw_text.split(";") if p.strip()]
        valid = [p for p in parts if p]
        if len(valid) >= 2:
            return valid

    # 2. Kiểm tra dấu nháy đơn ' (hỗ trợ cả dạng 'mục 1' 'mục 2' lẫn mục 1 ' mục 2)
    if "'" in raw_text:
        parts = [p.strip().strip("[]\"").strip() for p in raw_text.split("'") if p.strip()]
        valid = [p for p in parts if p]
        if len(valid) >= 2:
            return valid

    # 3. Tìm tất cả các cụm nằm trong ngoặc vuông [...]
    matches = re.findall(r"\[(.*?)\]", raw_text)
    choices = [m.strip().strip("'\"").strip() for m in matches if m.strip()]
    if len(choices) >= 2:
        return choices

    # 4. Dự phòng nếu người dùng gõ ngăn cách bằng dấu phẩy hoặc gạch đứng
    if "," in raw_text:
        fallback = [c.strip().strip("[]'\"").strip() for c in raw_text.split(",") if c.strip()]
        valid = [c for c in fallback if c]
        if len(valid) >= 2:
            return valid

    if "|" in raw_text:
        fallback = [c.strip().strip("[]'\"").strip() for c in raw_text.split("|") if c.strip()]
        valid = [c for c in fallback if c]
        if len(valid) >= 2:
            return valid

    return []


class GruCog(commands.Cog, name="Gru"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def run_gru_spin(
        self,
        user: discord.User | discord.Member,
        choices: List[str],
        send_func,
        edit_func
    ):
        """Thực hiện hiệu ứng quay số ngẫu nhiên mượt mà với guồng quay đa frame."""
        winner = random.choice(choices)
        choices_display = " ; ".join([f"`{c}`" for c in choices])

        # Tạo chuỗi xoay vòng lặp đủ lớn để mô phỏng 20 frame trôi liên tục không bị lỗi index
        pool = choices * 25
        # Chọn index đích cách đầu ít nhất 22 bước để frame -20 luôn an toàn
        target_idx = [i for i in range(22, len(pool) - 1) if pool[i] == winner][0]

        # 6 frame quay trước khi chốt kết quả, tốc độ giảm dần tự nhiên
        frames = [
    {
        "idx": target_idx - 20,
        "title": "🎰 VÒNG QUAY MAY MẮN: ĐANG KHỞI ĐỘNG...",
        "progress": "[ ▰▱▱▱▱▱ ] 05% • Bánh xe số phận bắt đầu chuyển động... 🌱",
        "icon": "🎲",
        "color": discord.Color.blue(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 19,
        "title": "🎰 VÒNG QUAY MAY MẮN: BẮT ĐẦU TĂNG TỐC!",
        "progress": "[ ▰▱▱▱▱▱ ] 10% • Những con số bắt đầu lướt qua... 💨",
        "icon": "💨",
        "color": discord.Color.blue(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 18,
        "title": "🎰 VÒNG QUAY MAY MẮN: VÀO GUỒNG! ⚡",
        "progress": "[ ▰▰▱▱▱▱ ] 15% • Vòng quay đang nóng dần lên... 🔥",
        "icon": "⚡",
        "color": discord.Color.purple(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 17,
        "title": "🎰 VÒNG QUAY MAY MẮN: TỐC ĐỘ TĂNG DẦN!",
        "progress": "[ ▰▰▱▱▱▱ ] 20% • Không thể nhìn rõ những con số! 💫",
        "icon": "💫",
        "color": discord.Color.purple(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 16,
        "title": "🎰 VÒNG QUAY MAY MẮN: QUAY NHANH HƠN NỮA!",
        "progress": "[ ▰▰▱▱▱▱ ] 25% • Vận may đang được định đoạt... 🎲",
        "icon": "🎲",
        "color": discord.Color.purple(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 15,
        "title": "🎰 VÒNG QUAY MAY MẮN: BỨT TỐC! 🚀",
        "progress": "[ ▰▰▰▱▱▱ ] 30% • Bánh xe đang quay với tốc độ chóng mặt! 🌪️",
        "icon": "🚀",
        "color": discord.Color.magenta(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 14,
        "title": "🔥 VÒNG QUAY MAY MẮN: TỐC ĐỘ CAO!",
        "progress": "[ ▰▰▰▱▱▱ ] 35% • Hàng loạt con số vụt qua trước mắt... 💥",
        "icon": "🔥",
        "color": discord.Color.magenta(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 13,
        "title": "⚡ VÒNG QUAY MAY MẮN: KHÔNG THỂ DỪNG LẠI!",
        "progress": "[ ▰▰▰▱▱▱ ] 40% • Vòng quay đang đạt giới hạn! ⚡",
        "icon": "⚡",
        "color": discord.Color.magenta(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 12,
        "title": "🌪️ VÒNG QUAY MAY MẮN: SIÊU TỐC!",
        "progress": "[ ▰▰▰▰▱▱ ] 45% • Tất cả chỉ còn là một vệt sáng! ✨",
        "icon": "🌪️",
        "color": discord.Color.dark_purple(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 11,
        "title": "💥 VÒNG QUAY MAY MẮN: ĐẠT TỐC ĐỘ TỐI ĐA!",
        "progress": "[ ▰▰▰▰▱▱ ] 50% • THỜI KHẮC QUYẾT ĐỊNH ĐÃ ĐẾN! 🔥",
        "icon": "💥",
        "color": discord.Color.dark_purple(),
        "delay": 0.15
    },
    {
        "idx": target_idx - 10,
        "title": "🔥 VÒNG QUAY MAY MẮN: CỰC HẠN!",
        "progress": "[ ▰▰▰▰▱▱ ] 55% • Vận may đang xoay chuyển... 🎰",
        "icon": "🔥",
        "color": discord.Color.red(),
        "delay": 0.18
    },
    {
        "idx": target_idx - 9,
        "title": "🎯 VÒNG QUAY MAY MẮN: BẮT ĐẦU GIẢM TỐC!",
        "progress": "[ ▰▰▰▰▱▱ ] 60% • Bánh xe bắt đầu chậm lại... ⏳",
        "icon": "🔄",
        "color": discord.Color.orange(),
        "delay": 0.22
    },
    {
        "idx": target_idx - 8,
        "title": "🎯 VÒNG QUAY MAY MẮN: NHỮNG NHỊP QUAY ĐẦU TIÊN...",
        "progress": "[ ▰▰▰▰▱▱ ] 65% • Kết quả đang dần hé lộ... 👀",
        "icon": "👀",
        "color": discord.Color.orange(),
        "delay": 0.28
    },
    {
        "idx": target_idx - 7,
        "title": "🎯 VÒNG QUAY MAY MẮN: CHẬM LẠI RỒI!",
        "progress": "[ ▰▰▰▰▰▱ ] 70% • Từng con số bắt đầu hiện rõ... 🔍",
        "icon": "🔍",
        "color": discord.Color.gold(),
        "delay": 0.35
    },
    {
        "idx": target_idx - 6,
        "title": "🎰 VÒNG QUAY MAY MẮN: ĐANG TIẾN GẦN KẾT QUẢ!",
        "progress": "[ ▰▰▰▰▰▱ ] 75% • Liệu ai sẽ là người may mắn? 🍀",
        "icon": "🍀",
        "color": discord.Color.gold(),
        "delay": 0.45
    },
    {
        "idx": target_idx - 5,
        "title": "👀 VÒNG QUAY MAY MẮN: CÒN 5 BƯỚC NỮA!",
        "progress": "[ ▰▰▰▰▰▱ ] 80% • Căng thẳng đang lên đến đỉnh điểm... 💓",
        "icon": "💓",
        "color": discord.Color.gold(),
        "delay": 0.55
    },
    {
        "idx": target_idx - 4,
        "title": "😱 VÒNG QUAY MAY MẮN: KẾT QUẢ SẮP LỘ DIỆN!",
        "progress": "[ ▰▰▰▰▰▱ ] 85% • Chỉ còn vài nhịp quay cuối cùng! 🎲",
        "icon": "😱",
        "color": discord.Color.orange(),
        "delay": 0.70
    },
    {
        "idx": target_idx - 3,
        "title": "🤏 VÒNG QUAY MAY MẮN: SÁT NÚT RỒI!",
        "progress": "[ ▰▰▰▰▰▰ ] 90% • Một bước nữa thôi... 🍀",
        "icon": "🤏",
        "color": discord.Color.orange(),
        "delay": 0.85
    },
    {
        "idx": target_idx - 2,
        "title": "💓 VÒNG QUAY MAY MẮN: NHỊP QUAY CUỐI!",
        "progress": "[ ▰▰▰▰▰▰ ] 94% • Tất cả đang nín thở chờ đợi... 🤫",
        "icon": "💓",
        "color": discord.Color.red(),
        "delay": 1.00
    },
    {
        "idx": target_idx - 1,
        "title": "🏆 VÒNG QUAY MAY MẮN: CHUẨN BỊ CÔNG BỐ!",
        "progress": "[ ▰▰▰▰▰▰ ] 99% • VẬN MAY SẼ GỌI TÊN AI?! 🎯",
        "icon": "🏆",
        "color": discord.Color.gold(),
        "delay": 1.30
    },
]

        def render_slot_box(top_item: str, mid_item: str, bot_item: str, icon: str) -> str:
            return (
                "```text\n"
                "┌───────────────────────────────────────┐\n"
                f"     ▫️   {top_item}\n"
                f"  ▶  {icon}   [ {mid_item} ]   ◀\n"
                f"     ▫️   {bot_item}\n"
                "└───────────────────────────────────────┘\n"
                "```"
            )

        # Chạy frame đầu tiên
        f0 = frames[0]
        step_idx = f0["idx"]
        top_txt = pool[step_idx - 1]
        mid_txt = pool[step_idx]
        bot_txt = pool[step_idx + 1]

        embed0 = discord.Embed(
            title=f0["title"],
            description=(
                f"👤 **Người quay:** {user.mention}\n"
                f"📋 **Các lựa chọn:** {choices_display}\n\n"
                f"{render_slot_box(top_txt, mid_txt, bot_txt, f0['icon'])}\n"
                f"*{f0['progress']}*"
            ),
            color=f0["color"]
        )
        embed0.set_footer(text="Lệnh /gru • Hệ thống lựa chọn ngẫu nhiên")
        await send_func(embed=embed0)
        await asyncio.sleep(f0["delay"])

        # Chạy các frame tiếp theo
        for f in frames[1:]:
            s_idx = f["idx"]
            t_txt = pool[s_idx - 1]
            m_txt = pool[s_idx]
            b_txt = pool[s_idx + 1]

            embed_frame = discord.Embed(
                title=f["title"],
                description=(
                    f"👤 **Người quay:** {user.mention}\n"
                    f"📋 **Các lựa chọn:** {choices_display}\n\n"
                    f"{render_slot_box(t_txt, m_txt, b_txt, f['icon'])}\n"
                    f"*{f['progress']}*"
                ),
                color=f["color"]
            )
            embed_frame.set_footer(text="Lệnh /gru • Hệ thống lựa chọn ngẫu nhiên")
            try:
                await edit_func(embed=embed_frame)
            except Exception:
                return

            await asyncio.sleep(f["delay"])

        # Frame cuối: Nổ kết quả chiến thắng!
        quotes = [
            "Vũ trụ đã mách bảo, chốt luôn món này không hối hận nhé! 😎",
            "Trời tính không bằng Gru tính, triển khai ngay thôi! ✨",
            "Khỏi cần đắn đo suy nghĩ nữa, định mệnh đã an bài! 🎯",
            "Món ngon hay việc xịn đã tới, tới công chuyện luôn đi! 🔥",
            "Quyết định thế đi, cấm quay xe nha! ٩(ˊᗜˋ*)و",
        ]
        quote = random.choice(quotes)

        embed_final = discord.Embed(
            title="🎉 KẾT QUẢ ĐÃ ĐƯỢC CHỌN! ⸜(｡˃ ᵕ ˂ )⸝♡",
            description=(
                f"👤 **Người yêu cầu:** {user.mention}\n"
                f"📋 **Danh sách lựa chọn:** {choices_display}\n\n"
                f"```text\n"
                f"╔═══════════════════════════════════════╗\n"
                f"       ✨ 🏆 [ {winner} ] 🏆 ✨       \n"
                f"╚═══════════════════════════════════════╝\n"
                f"```\n"
                f"💡 *{quote}*"
            ),
            color=discord.Color.green()
        )
        embed_final.set_footer(text=f"Lệnh /gru • Đã chọn ngẫu nhiên 1 trong {len(choices)} mục")
        try:
            await edit_func(embed=embed_final)
        except Exception:
            pass

    @app_commands.command(
        name="gru",
        description="Quay số may mắn chọn 1 mục ngẫu nhiên. Ngăn cách bằng dấu ; hoặc ' hoặc [ ]"
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(
        lua_chon="Nhập các lựa chọn, ngăn cách bằng dấu ; hoặc ' hoặc [ ] (vd: Phở; Bún; Cơm)"
    )
    async def cmd_gru(self, interaction: discord.Interaction, lua_chon: str):
        choices = parse_choices(lua_chon)
        if len(choices) < 2:
            await interaction.response.send_message(
                "❌ **Vui lòng nhập ít nhất 2 lựa chọn!**\n"
                "👉 **Cách nhập rất đơn giản:**\n"
                "• Dùng dấu `;`: `/gru lua_chon: Cơm sườn; Phở bò; Bún đậu; Trà sữa`\n"
                "• Dùng dấu `'`: `/gru lua_chon: 'Cơm sườn' 'Phở bò' 'Bún đậu'` hoặc `Cơm ' Phở ' Bún`\n"
                "• Dùng dấu `[ ]`: `/gru lua_chon: [Cơm sườn] [Phở bò] [Bún đậu]`",
                ephemeral=True
            )
            return

        async def send(embed):
            await interaction.response.send_message(embed=embed)

        async def edit(embed):
            await interaction.edit_original_response(embed=embed)

        await self.run_gru_spin(interaction.user, choices, send, edit)

    # Hỗ trợ cả lệnh chat thường !gru
    @commands.command(name="gru")
    async def prefix_gru(self, ctx: commands.Context, *, lua_chon: str = ""):
        choices = parse_choices(lua_chon)
        if len(choices) < 2:
            await ctx.send(
                "❌ **Vui lòng nhập ít nhất 2 lựa chọn!**\n"
                "👉 **Ví dụ:** `!gru Cơm sườn; Phở bò; Bún đậu` hoặc `'Cơm' 'Phở' 'Bún'`"
            )
            return

        msg = None

        async def send(embed):
            nonlocal msg
            msg = await ctx.send(embed=embed)

        async def edit(embed):
            nonlocal msg
            if msg:
                await msg.edit(embed=embed)

        await self.run_gru_spin(ctx.author, choices, send, edit)


async def setup(bot: commands.Bot):
    await bot.add_cog(GruCog(bot))
