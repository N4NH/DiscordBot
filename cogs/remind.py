import time
import re
from typing import Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands, tasks

import database

def parse_hms_time(time_str: str) -> Tuple[Optional[int], str]:
    """
    Phân tích chuỗi thời gian theo định dạng hours:minutes:seconds.
    Hỗ trợ:
      - 3 phần: h:m:s (Ví dụ: 1:30:00, 0:15:30, 0:0:10)
      - 2 phần: m:s (Ví dụ: 15:30, 5:0)
    Trả về (tổng_số_giây, chuỗi_mô_tả_thời_gian).
    """
    time_str = time_str.strip()
    parts = [p.strip() for p in time_str.split(":")]
    
    try:
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        elif len(parts) == 2:
            hours = 0
            minutes = int(parts[0])
            seconds = int(parts[1])
        elif len(parts) == 1:
            hours = 0
            minutes = 0
            seconds = int(parts[0])
        else:
            return None, "Định dạng không hợp lệ. Vui lòng nhập theo dạng `giờ:phút:giây` (Ví dụ: `0:15:00` hoặc `1:30:00`)."

        if hours < 0 or minutes < 0 or seconds < 0:
            return None, "Thời gian không được là số âm!"

        total_seconds = hours * 3600 + minutes * 60 + seconds
        if total_seconds <= 0:
            return None, "Thời gian hẹn phải lớn hơn 0 giây!"

        if total_seconds > 86400 * 30:  # Tối đa 30 ngày
            return None, "Thời gian hẹn tối đa là 30 ngày (720:00:00)!"

        # Tạo chuỗi mô tả thân thiện
        desc_parts = []
        if hours > 0:
            desc_parts.append(f"{hours} giờ")
        if minutes > 0:
            desc_parts.append(f"{minutes} phút")
        if seconds > 0 or not desc_parts:
            desc_parts.append(f"{seconds} giây")

        return total_seconds, " ".join(desc_parts)

    except ValueError:
        return None, "Thời gian phải là các chữ số ngăn cách bằng dấu hai chấm `:` (Ví dụ: `0:15:00` cho 15 phút, `1:30:00` cho 1 tiếng 30 phút)."


class RemindCog(commands.Cog, name="Remind"):
    """Hệ thống nhắc nhở hẹn giờ tự động tag tên người dùng."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.check_reminders_task.start()

    async def cog_unload(self):
        self.check_reminders_task.cancel()

    @tasks.loop(seconds=5)
    async def check_reminders_task(self):
        """Vòng lặp chạy ngầm mỗi 5 giây kiểm tra và gửi lời nhắc đã đến hạn."""
        now = time.time()
        try:
            due_reminders = database.get_due_reminders(now)
            for r in due_reminders:
                remind_id = r["id"]
                channel_id = r["channel_id"]
                user_id = r["user_id"]
                note = r["message"]
                remind_at = r["remind_at"]

                # Tìm kênh gửi tin nhắn
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    try:
                        channel = await self.bot.fetch_channel(channel_id)
                    except Exception:
                        channel = None

                embed = discord.Embed(
                    title="⏰ ĐẾN GIỜ RỒI! BẠN CÓ MỘT LỜI NHẮC 🔔",
                    description=f">>> {note}",
                    color=discord.Color.gold()
                )
                embed.add_field(
                    name="⏱️ Thời điểm hẹn",
                    value=f"<t:{int(remind_at)}:F> (<t:{int(remind_at)}:R>)",
                    inline=True
                )
                embed.set_footer(text="Hệ thống Nhắc Nhở Tự Động • Bánh Gấu Bot")

                sent = False
                if channel:
                    try:
                        await channel.send(content=f"🔔 <@{user_id}> ơi, có lời nhắc nè!", embed=embed)
                        sent = True
                    except Exception as e:
                        print(f"[Remind Error] Không thể gửi vào channel {channel_id}: {e}", flush=True)

                # Fallback gửi qua tin nhắn riêng (DM) nếu kênh bị xóa hoặc bot không có quyền gửi
                if not sent:
                    try:
                        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                        if user:
                            await user.send(content=f"🔔 <@{user_id}>, bạn có lời nhắc đã đến hạn!", embed=embed)
                    except Exception as e:
                        print(f"[Remind Error] Không thể gửi DM cho user {user_id}: {e}", flush=True)

                # Xóa nhắc nhở khỏi cơ sở dữ liệu sau khi thông báo
                database.delete_reminder(remind_id)

        except Exception as e:
            print(f"[Remind Task Error] {e}", flush=True)

    @check_reminders_task.before_loop
    async def before_check_reminders(self):
        try:
            await self.bot.wait_until_ready()
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────────────────────────
    @app_commands.command(
        name="remind",
        description="Đặt lịch nhắc nhở theo giờ:phút:giây (hours:minutes:seconds) và tag tên bạn khi đến hạn"
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(
        thoi_gian="Nhập theo dạng hours:minutes:seconds (Ví dụ: 0:15:00 cho 15 phút, 1:30:00 cho 1 tiếng rưỡi)",
        ghi_chu="Nội dung công việc hoặc việc cần ghi nhớ"
    )
    async def slash_remind(self, interaction: discord.Interaction, thoi_gian: str, ghi_chu: str):
        total_seconds, desc = parse_hms_time(thoi_gian)
        if total_seconds is None:
            await interaction.response.send_message(f"❌ {desc}", ephemeral=True)
            return

        now = time.time()
        remind_at = now + total_seconds
        remind_timestamp = int(remind_at)

        guild_id = interaction.guild_id if interaction.guild else None
        channel_id = interaction.channel_id

        remind_id = database.add_reminder(
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=interaction.user.id,
            message=ghi_chu,
            remind_at=remind_at
        )

        embed = discord.Embed(
            title="✅ Đã Đặt Lời Nhắc Thành Công!",
            description=(
                f"👤 **Người nhận:** {interaction.user.mention}\n"
                f"📝 **Ghi chú:** `{ghi_chu}`\n"
                f"⏳ **Thời gian đếm ngược:** **{desc}**\n"
                f"⏰ **Sẽ nhắc vào lúc:** <t:{remind_timestamp}:F> (<t:{remind_timestamp}:R>)\n"
                f"🆔 **Mã nhắc nhở:** `#{remind_id}`"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text="Bot sẽ tự động tag bạn vào kênh này khi chuông reo!")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="remind_list",
        description="Xem danh sách các lời nhắc đang chờ chuông của bạn"
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    async def slash_remind_list(self, interaction: discord.Interaction):
        user_reminders = database.get_user_reminders(interaction.user.id)
        if not user_reminders:
            await interaction.response.send_message("📭 Bạn hiện không có lời nhắc nào đang chờ!", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📋 Danh Sách Nhắc Nhở Của {interaction.user.display_name}",
            color=discord.Color.blue()
        )

        lines = []
        for r in user_reminders:
            r_id = r["id"]
            msg = r["message"]
            remind_at = int(r["remind_at"])
            lines.append(f"`#{r_id}` • <t:{remind_at}:R> (<t:{remind_at}:t>)\n└ 📝 *{msg}*")

        embed.description = "\n\n".join(lines)
        embed.set_footer(text="Dùng /remind_cancel <id> nếu bạn muốn hủy lời nhắc.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="remind_cancel",
        description="Hủy một lời nhắc của bạn theo mã ID"
    )
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(ma_id="Mã số của lời nhắc (xem trong /remind_list)")
    async def slash_remind_cancel(self, interaction: discord.Interaction, ma_id: int):
        user_reminders = database.get_user_reminders(interaction.user.id)
        target = next((r for r in user_reminders if r["id"] == ma_id), None)
        if not target:
            await interaction.response.send_message(f"❌ Không tìm thấy lời nhắc `#{ma_id}` của bạn!", ephemeral=True)
            return

        database.delete_reminder(ma_id)
        await interaction.response.send_message(f"🗑️ Đã hủy thành công lời nhắc `#{ma_id}` (*{target['message']}*)!", ephemeral=True)

    # ─────────────────────────────────────────────────────────────
    # PREFIX COMMANDS (!remind, !reminders)
    # ─────────────────────────────────────────────────────────────
    @commands.command(name="remind", aliases=["nhac"])
    async def prefix_remind(self, ctx: commands.Context, thoi_gian: str, *, ghi_chu: str):
        """Lệnh prefix: !remind <giờ:phút:giây> <nội dung ghi chú>"""
        total_seconds, desc = parse_hms_time(thoi_gian)
        if total_seconds is None:
            await ctx.reply(f"❌ {desc}")
            return

        now = time.time()
        remind_at = now + total_seconds
        remind_timestamp = int(remind_at)

        remind_id = database.add_reminder(
            guild_id=ctx.guild.id if ctx.guild else None,
            channel_id=ctx.channel.id,
            user_id=ctx.author.id,
            message=ghi_chu,
            remind_at=remind_at
        )

        embed = discord.Embed(
            title="✅ Đã Đặt Lời Nhắc Thành Công!",
            description=(
                f"👤 **Người nhận:** {ctx.author.mention}\n"
                f"📝 **Ghi chú:** `{ghi_chu}`\n"
                f"⏳ **Thời gian đếm ngược:** **{desc}**\n"
                f"⏰ **Sẽ nhắc vào lúc:** <t:{remind_timestamp}:F> (<t:{remind_timestamp}:R>)\n"
                f"🆔 **Mã nhắc nhở:** `#{remind_id}`"
            ),
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="remindlist", aliases=["reminders"])
    async def prefix_remind_list(self, ctx: commands.Context):
        """Lệnh prefix: xem danh sách nhắc nhở"""
        user_reminders = database.get_user_reminders(ctx.author.id)
        if not user_reminders:
            await ctx.reply("📭 Bạn hiện không có lời nhắc nào đang chờ!")
            return

        embed = discord.Embed(
            title=f"📋 Danh Sách Nhắc Nhở Của {ctx.author.display_name}",
            color=discord.Color.blue()
        )

        lines = []
        for r in user_reminders:
            r_id = r["id"]
            msg = r["message"]
            remind_at = int(r["remind_at"])
            lines.append(f"`#{r_id}` • <t:{remind_at}:R> (<t:{remind_at}:t>)\n└ 📝 *{msg}*")

        embed.description = "\n\n".join(lines)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindCog(bot))
