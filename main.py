import os
import sys
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import database

# Đảm bảo hiển thị tiếng Việt trên terminal Windows không bị lỗi encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Tải token từ .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

class MovieBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Tự động nạp (load) tất cả các module cogs trong thư mục cogs/
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if os.path.exists(cogs_dir):
            for filename in os.listdir(cogs_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    cog_name = f"cogs.{filename[:-3]}"
                    await self.load_extension(cog_name)
                    print(f"-> Đã nạp module: {cog_name}", flush=True)

        # Đăng ký Persistent View cho các bài đăng 2 trang trong kênh chi tiết phim
        from helpers import MovieShowcaseView, create_showcase_embed_page1
        self.add_view(MovieShowcaseView())

        # Đồng bộ các lệnh Slash command với Discord
        try:
            synced = await self.tree.sync()
            print(f"Đã đồng bộ {len(synced)} lệnh slash command thành công!", flush=True)
        except Exception as e:
            print(f"Lỗi khi đồng bộ slash command: {e}", flush=True)

    async def on_ready(self):
        print(f"✅ Bot đã đăng nhập thành công với tên: {self.user} (ID: {self.user.id})", flush=True)
        # Đồng bộ lệnh cấp server (guild commands) để các lệnh mới như /remind hiện tức thì 0 giây
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"-> Đã đồng bộ {len(synced)} lệnh slash command tức thì cho server '{guild.name}'!", flush=True)
            except Exception as e:
                print(f"Lỗi đồng bộ slash command cho server {guild.name}: {e}", flush=True)

        # Nâng cấp các bài đăng showcase cũ (như bài phim đã đăng) sang giao diện 2 trang có nút bấm
        from helpers import MovieShowcaseView, create_showcase_embed_page1
        for guild in self.guilds:
            try:
                showcase_channel_id = database.get_showcase_channel(guild.id)
                if showcase_channel_id:
                    channel = self.get_channel(showcase_channel_id) or await self.fetch_channel(showcase_channel_id)
                    if channel:
                        movies = database.get_showcase_movies(guild.id)
                        for m in movies:
                            msg_id = m.get("showcase_message_id")
                            if msg_id:
                                try:
                                    msg = await channel.fetch_message(msg_id)
                                    embed = create_showcase_embed_page1(m)
                                    await msg.edit(embed=embed, view=MovieShowcaseView())
                                except Exception:
                                    pass
            except Exception:
                pass

bot = MovieBot()

@bot.tree.command(name="sync", description="Đồng bộ ngay lập tức toàn bộ slash command mới nhất vào server")
@app_commands.default_permissions(administrator=True)
async def slash_sync(interaction: discord.Interaction):
    """Lệnh /sync giúp đồng bộ ngay lập tức toàn bộ lệnh mới."""
    await interaction.response.defer(ephemeral=True)
    try:
        interaction.client.tree.copy_global_to(guild=interaction.guild)
        synced = await interaction.client.tree.sync(guild=interaction.guild)
        await interaction.followup.send(
            f"✅ Đã đồng bộ thành công **{len(synced)}** lệnh slash command cho server!\n"
            f"👉 Nhấn `Ctrl + R` trên Discord (hoặc vuốt tắt app Discord trên điện thoại rồi mở lại) để thấy các lệnh mới như `/remind` ngay nhé!"
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Lỗi khi đồng bộ: {e}")

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_commands(ctx: commands.Context):
    """Lệnh !sync giúp đồng bộ lại slash command."""
    msg = await ctx.send("⏳ Đang đồng bộ lệnh...")
    try:
        ctx.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await ctx.bot.tree.sync(guild=ctx.guild)
        await msg.edit(content=f"✅ Đã đồng bộ thành công **{len(synced)}** slash command cho server!\n👉 Nhấn `Ctrl + R` trên Discord để tải lại giao diện nhé.")
    except Exception as e:
        await msg.edit(content=f"❌ Lỗi đồng bộ: {e}")


if __name__ == "__main__":
    database.init_db()
    if not TOKEN:
        print("Lỗi: Không tìm thấy DISCORD_TOKEN trong file .env!", flush=True)
    else:
        bot.run(TOKEN)
