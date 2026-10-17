import asyncio
import os
import re
import uuid
from typing import Optional, Set
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from gemini_browser import GeminiBrowserClient, split_discord_message

# Danh sách người dùng được phép sử dụng Gemini (cấu hình trong file .env qua ALLOWED_AI_USERS)
DEFAULT_ALLOWED_USERS: Set[str] = set()

IMAGE_URL_REGEX = re.compile(
    r'(https?://[^\s]+?\.(?:png|jpg|jpeg|webp|gif|bmp)(?:\?[^\s]*)?|https?://(?:cdn|media)\.discordapp\.(?:com|net)/attachments/[^\s]+)',
    re.IGNORECASE
)

def get_allowed_users() -> Set[str]:
    """Lấy danh sách các username hoặc user ID được phép sử dụng Gemini từ .env."""
    users = set(DEFAULT_ALLOWED_USERS)
    env_users = os.getenv("ALLOWED_AI_USERS", "")
    if env_users:
        for u in env_users.split(","):
            u_clean = u.strip().lower()
            if u_clean:
                users.add(u_clean)
    return users

def is_user_authorized(user: discord.User | discord.Member) -> bool:
    """Kiểm tra quyền truy cập của người dùng."""
    allowed = get_allowed_users()
    username = (user.name or "").lower().strip()
    user_id = str(user.id).strip()
    global_name = (user.global_name or "").lower().strip()

    return (
        username in allowed
        or user_id in allowed
        or global_name in allowed
    )

async def download_image_attachment(attachment: discord.Attachment) -> Optional[str]:
    """Tải file ảnh đính kèm từ Discord về thư mục tạm."""
    is_img = (attachment.content_type and attachment.content_type.startswith("image/"))
    ext = os.path.splitext(attachment.filename)[1].lower()
    if not is_img and ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]:
        return None

    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_images")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{attachment.id}_{attachment.filename}")
    await attachment.save(temp_path)
    return temp_path

async def download_image_from_url(url: str) -> Optional[str]:
    """Tải ảnh từ đường dẫn URL (như link Discord hoặc web) về thư mục tạm."""
    try:
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_images")
        os.makedirs(temp_dir, exist_ok=True)
        filepath = os.path.join(temp_dir, f"url_{uuid.uuid4().hex[:8]}.png")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    with open(filepath, "wb") as f:
                        f.write(data)
                    return filepath
    except Exception:
        pass
    return None


# Chế độ chờ (Standby Mode): Tạm ẩn việc mở trình duyệt Edge, giữ lại toàn bộ code để kích hoạt lại sau
GEMINI_STANDBY_MODE = os.getenv("GEMINI_STANDBY", "true").lower() in ["true", "1", "yes"]
STANDBY_MESSAGE = (
    "🛠️ **Tính năng Gemini hiện đang tạm đóng để nâng cấp/bảo trì.**\n"
    "👉 Bạn có thể sử dụng lệnh `/gpt <câu_hỏi>` để trò chuyện với AI thông minh nhé!"
)

class GeminiCog(commands.Cog, name="Gemini"):
    """
    Cog tích hợp Gemini Web trực tiếp qua Chrome for Testing (CfT) / Microsoft Edge.
    - Đang ở chế độ chờ (Standby), không tự động bật Edge hay tốn tài nguyên.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Chỉ khởi tạo browser client khi không ở chế độ chờ
        self.client = None if GEMINI_STANDBY_MODE else GeminiBrowserClient(headless=False)
        self.current_user: Optional[str] = None

        # Đăng ký Message Context Menu để chuột phải vào tin nhắn bất kỳ và hỏi Gemini
        self.ctx_menu = app_commands.ContextMenu(
            name="Hỏi Gemini tin nhắn này",
            callback=self.context_menu_gemini
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def _safe_start(self):
        if not self.client:
            return
        try:
            await self.client.start()
        except Exception as e:
            print(f"[GeminiCog] Chưa thể khởi chạy Gemini Browser tự động ({e}). Trình duyệt sẽ được khởi động lại khi có lệnh gọi.", flush=True)

    async def cog_load(self):
        """Khởi động trang Gemini nếu không ở chế độ chờ."""
        if GEMINI_STANDBY_MODE:
            print("[GeminiCog] Tính năng Gemini đang ở chế độ chờ (Standby) - Đã tắt tự động mở Edge.", flush=True)
            return
        asyncio.create_task(self._safe_start())

    async def cog_unload(self):
        """Khi cog bị reload hoặc bot tắt, dọn dẹp trình duyệt và context menu."""
        try:
            self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)
        except Exception:
            pass
        if self.client:
            try:
                await self.client.stop()
            except Exception:
                pass

    async def _safe_send_response(self, interaction: discord.Interaction, chunks: list[str]):
        """Gửi tin nhắn an toàn, nếu webhook interaction bị lỗi (ví dụ 404) sẽ fallback sang channel.send."""
        for idx, chunk in enumerate(chunks):
            try:
                await interaction.followup.send(chunk)
            except discord.NotFound:
                if interaction.channel:
                    await interaction.channel.send(chunk)
            except Exception:
                if interaction.channel:
                    await interaction.channel.send(chunk)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Lắng nghe tin nhắn khi người dùng tag @Bot:
        - Hoàn toàn KHÔNG CẦN Message Content Intent (Discord luôn cấp quyền đọc khi bot được tag).
        - Hoàn toàn KHÔNG CÓ HỘP THOẠI SLASH (nhắn tin bình thường, dán ảnh Ctrl+V, kéo thả file).
        - Hỗ trợ Reply tin nhắn của người khác và tag @Bot để hỏi về tin nhắn đó.
        """
        # Bỏ qua tin nhắn từ chính bot hoặc bot khác
        if message.author.bot:
            return

        # Kiểm tra xem bot có được tag trong tin nhắn không
        if not self.bot.user or self.bot.user not in message.mentions:
            return

        # Nếu đang ở chế độ chờ, phản hồi thông báo và không bật browser
        if GEMINI_STANDBY_MODE:
            await message.reply(STANDBY_MESSAGE, mention_author=False)
            return

        # 1. Kiểm tra phân quyền người dùng
        if not is_user_authorized(message.author):
            await message.reply(
                "🚫 **Từ chối truy cập!** Bạn không có quyền sử dụng Gemini trên bot này.",
                mention_author=False
            )
            return

        # 2. Kiểm tra xem trình duyệt có đang bận không
        if self.client.is_busy:
            busy_info = f" bởi **{self.current_user}**" if self.current_user else ""
            await message.reply(
                f"⚠️ **Gemini hiện đang bận!** Đang có câu hỏi được xử lý{busy_info}.\n"
                f"👉 Vui lòng đợi trong giây lát để lượt này hoàn tất rồi thử lại nhé!",
                mention_author=False
            )
            return

        # 3. Lọc bỏ tag bot khỏi nội dung câu hỏi
        clean_text = message.content
        if self.bot.user:
            clean_text = clean_text.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()

        # 4. Kiểm tra xem có đang Reply tin nhắn của người khác không
        ref_message: Optional[discord.Message] = None
        if message.reference and message.reference.message_id:
            try:
                ref_message = await message.channel.fetch_message(message.reference.message_id)
            except Exception:
                ref_message = None

        prompt_parts = []
        target_author = None
        if ref_message:
            target_author = ref_message.author.display_name
            if ref_message.content.strip():
                prompt_parts.append(f"Câu hỏi của {target_author}: \"{ref_message.content.strip()}\"")

        if clean_text:
            if ref_message:
                prompt_parts.append(f"Yêu cầu của tôi: \"{clean_text}\"")
            else:
                prompt_parts.append(clean_text)

        # 5. Thu thập ảnh: Ưu tiên ảnh của tin nhắn hiện tại, sau đó đến ảnh của tin nhắn Reply
        attachment_to_use: Optional[discord.Attachment] = None
        if message.attachments:
            attachment_to_use = message.attachments[0]
        elif ref_message and ref_message.attachments:
            attachment_to_use = ref_message.attachments[0]

        raw_combined_prompt = "\n".join(prompt_parts)

        # Kiểm tra xem có dữ liệu nào không
        if not raw_combined_prompt and not attachment_to_use:
            await message.reply(
                "💡 **Bạn đã tag Gemini!** Hãy gửi câu hỏi hoặc dán ảnh kèm theo (Ctrl + V) để tôi hỗ trợ nhé.",
                mention_author=False
            )
            return

        self.current_user = message.author.display_name
        image_path: Optional[str] = None

        async with message.channel.typing():
            try:
                # Tải file ảnh đính kèm nếu có
                if attachment_to_use:
                    image_path = await download_image_attachment(attachment_to_use)

                # Nếu không có file đính kèm mà trong text có link ảnh
                if not image_path and raw_combined_prompt:
                    match = IMAGE_URL_REGEX.search(raw_combined_prompt)
                    if match:
                        img_url = match.group(1)
                        image_path = await download_image_from_url(img_url)
                        raw_combined_prompt = raw_combined_prompt.replace(img_url, "").strip()

                final_prompt = raw_combined_prompt if raw_combined_prompt.strip() else "Hãy phân tích hình ảnh này và đưa ra câu trả lời chi tiết, chính xác giúp tôi."
                answer = await self.client.ask(final_prompt, image_path=image_path)

                full_response = answer
                chunks = split_discord_message(full_response, max_length=1900)

                target_reply = ref_message if ref_message else message
                await target_reply.reply(chunks[0], mention_author=False)
                for chunk in chunks[1:]:
                    await message.channel.send(chunk)

            except Exception as e:
                await message.reply(f"⚠️ **Lỗi:** `{e}`", mention_author=False)
            finally:
                self.current_user = None
                if image_path and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception:
                        pass

    @app_commands.command(
        name="gemini",
        description="Gửi bất cứ thứ gì bạn muốn hỏi đến Gemini (Văn bản, link ảnh, file ảnh...)"
    )
    @app_commands.describe(
        input="Nhập bất cứ thứ gì: câu hỏi, văn bản, hoặc link ảnh",
        file="Đính kèm file hoặc ảnh từ máy tính (tùy chọn)"
    )
    async def slash_gemini(
        self,
        interaction: discord.Interaction,
        input: Optional[str] = None,
        file: Optional[discord.Attachment] = None
    ):
        """Slash command /gemini [input] [file]"""
        if GEMINI_STANDBY_MODE:
            await interaction.response.send_message(STANDBY_MESSAGE, ephemeral=True)
            return

        # 1. Kiểm tra phân quyền
        if not is_user_authorized(interaction.user):
            await interaction.response.send_message(
                "🚫 **Từ chối truy cập!** Bạn không có quyền sử dụng Gemini trên bot này.",
                ephemeral=True
            )
            return

        # 2. Kiểm tra có dữ liệu gửi đi không
        if not input and not file:
            await interaction.response.send_message(
                "⚠️ Bạn chưa nhập nội dung gì cả! Hãy nhập câu hỏi hoặc đính kèm ảnh nhé.",
                ephemeral=True
            )
            return

        # 3. Kiểm tra xem trình duyệt có đang bận không
        if self.client.is_busy:
            busy_info = f" bởi **{self.current_user}**" if self.current_user else ""
            await interaction.response.send_message(
                f"⚠️ **Gemini hiện đang bận!** Đang có câu hỏi được xử lý{busy_info}.\n"
                f"👉 Vui lòng đợi trong giây lát để lượt này hoàn tất rồi thử lại nhé!",
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        self.current_user = interaction.user.display_name

        image_path: Optional[str] = None
        raw_prompt = input or ""

        try:
            # Nếu có file ảnh đính kèm
            if file:
                image_path = await download_image_attachment(file)

            # Nếu trong ô input có chứa link ảnh trực tiếp -> Tự động tải về làm ảnh
            if not image_path and raw_prompt:
                match = IMAGE_URL_REGEX.search(raw_prompt)
                if match:
                    img_url = match.group(1)
                    image_path = await download_image_from_url(img_url)
                    # Bỏ link ảnh khỏi câu hỏi để prompt gọn gàng
                    raw_prompt = raw_prompt.replace(img_url, "").strip()

            final_prompt = raw_prompt if raw_prompt.strip() else "Hãy phân tích hình ảnh này và đưa ra thông tin chi tiết."
            answer = await self.client.ask(final_prompt, image_path=image_path)

            full_response = answer
            chunks = split_discord_message(full_response, max_length=1900)
            await self._safe_send_response(interaction, chunks)

        except Exception as e:
            msg = f"⚠️ **Đã xảy ra lỗi khi gửi yêu cầu đến Gemini:** `{e}`\nVui lòng thử lại sau giây lát!"
            await self._safe_send_response(interaction, [msg])
        finally:
            self.current_user = None
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass

    @commands.command(name="gemini", help="Hỏi Gemini Web (Gõ trực tiếp, đính kèm ảnh hoặc Reply tin nhắn)")
    async def prefix_gemini(self, ctx: commands.Context, *, input_text: Optional[str] = None):
        """
        Prefix command !gemini [bất cứ thứ gì]
        - Gửi bất cứ câu hỏi nào.
        - Kéo thả bao nhiêu ảnh tùy thích vào tin nhắn.
        - Reply tin nhắn của bất kỳ ai để Gemini phân tích cả câu hỏi lẫn ảnh của họ!
        """
        if GEMINI_STANDBY_MODE:
            await ctx.reply(STANDBY_MESSAGE, mention_author=False)
            return

        # 1. Kiểm tra phân quyền
        if not is_user_authorized(ctx.author):
            await ctx.reply(
                "🚫 **Từ chối truy cập!** Bạn không có quyền sử dụng Gemini trên bot này.",
                mention_author=False
            )
            return

        # 2. Kiểm tra xem trình duyệt có đang bận không
        if self.client.is_busy:
            busy_info = f" bởi **{self.current_user}**" if self.current_user else ""
            await ctx.reply(
                f"⚠️ **Gemini hiện đang bận!** Đang có câu hỏi được xử lý{busy_info}.\n"
                f"👉 Vui lòng đợi trong giây lát để lượt này hoàn tất rồi thử lại nhé!",
                mention_author=False
            )
            return

        # 3. Phân tích ngữ cảnh: Tin nhắn có đang Reply người khác không?
        ref_message: Optional[discord.Message] = None
        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                ref_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except Exception:
                ref_message = None

        # Thu thập toàn bộ nội dung câu hỏi
        prompt_parts = []
        target_author = None
        if ref_message:
            target_author = ref_message.author.display_name
            if ref_message.content.strip():
                prompt_parts.append(f"Câu hỏi của {target_author}: \"{ref_message.content.strip()}\"")

        if input_text and input_text.strip():
            if ref_message:
                prompt_parts.append(f"Yêu cầu của tôi: \"{input_text.strip()}\"")
            else:
                prompt_parts.append(input_text.strip())

        # Thu thập ảnh (từ tin nhắn hiện tại hoặc từ tin nhắn được Reply)
        attachment_to_use: Optional[discord.Attachment] = None
        if ctx.message.attachments:
            attachment_to_use = ctx.message.attachments[0]
        elif ref_message and ref_message.attachments:
            attachment_to_use = ref_message.attachments[0]

        # Kiểm tra xem có link ảnh trong prompt không
        raw_combined_prompt = "\n".join(prompt_parts)
        image_path: Optional[str] = None

        if not raw_combined_prompt and not attachment_to_use:
            await ctx.reply(
                "⚠️ Vui lòng nhập nội dung, gửi ảnh hoặc Reply một tin nhắn để Gemini hỗ trợ!",
                mention_author=False
            )
            return

        self.current_user = ctx.author.display_name

        async with ctx.typing():
            try:
                # 1. Ưu tiên tải ảnh từ file đính kèm
                if attachment_to_use:
                    image_path = await download_image_attachment(attachment_to_use)

                # 2. Nếu không có file đính kèm, tìm xem có link ảnh trong chữ không
                if not image_path and raw_combined_prompt:
                    match = IMAGE_URL_REGEX.search(raw_combined_prompt)
                    if match:
                        img_url = match.group(1)
                        image_path = await download_image_from_url(img_url)
                        raw_combined_prompt = raw_combined_prompt.replace(img_url, "").strip()

                final_prompt = raw_combined_prompt if raw_combined_prompt.strip() else "Hãy phân tích hình ảnh này và đưa ra câu trả lời chi tiết, chính xác giúp tôi."
                answer = await self.client.ask(final_prompt, image_path=image_path)

                full_response = answer
                chunks = split_discord_message(full_response, max_length=1900)

                target_msg = ref_message if ref_message else ctx.message
                await target_msg.reply(chunks[0], mention_author=False)
                for chunk in chunks[1:]:
                    await ctx.send(chunk)

            except Exception as e:
                await ctx.reply(f"⚠️ **Lỗi:** `{e}`", mention_author=False)
            finally:
                self.current_user = None
                if image_path and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception:
                        pass

    async def context_menu_gemini(self, interaction: discord.Interaction, message: discord.Message):
        """Xử lý khi người dùng click chuột phải vào tin nhắn -> Apps -> 'Hỏi Gemini tin nhắn này'."""
        if GEMINI_STANDBY_MODE:
            await interaction.response.send_message(STANDBY_MESSAGE, ephemeral=True)
            return

        if not is_user_authorized(interaction.user):
            await interaction.response.send_message(
                "🚫 **Từ chối truy cập!** Bạn không có quyền sử dụng Gemini trên bot này.",
                ephemeral=True
            )
            return

        if self.client.is_busy:
            busy_info = f" bởi **{self.current_user}**" if self.current_user else ""
            await interaction.response.send_message(
                f"⚠️ **Gemini hiện đang bận!** Đang có câu hỏi được xử lý{busy_info}.\n"
                f"👉 Vui lòng đợi trong giây lát để lượt này hoàn tất rồi thử lại nhé!",
                ephemeral=True
            )
            return

        content = message.content.strip()
        attachment = message.attachments[0] if message.attachments else None

        if not content and not attachment:
            await interaction.response.send_message(
                "⚠️ Tin nhắn này không có nội dung chữ hoặc hình ảnh để phân tích!",
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)
        self.current_user = interaction.user.display_name
        image_path: Optional[str] = None

        try:
            if attachment:
                image_path = await download_image_attachment(attachment)

            if not image_path and content:
                match = IMAGE_URL_REGEX.search(content)
                if match:
                    img_url = match.group(1)
                    image_path = await download_image_from_url(img_url)
                    content = content.replace(img_url, "").strip()

            prompt = content if content else "Hãy phân tích hình ảnh này và tóm tắt các điểm quan trọng."
            answer = await self.client.ask(prompt, image_path=image_path)

            full_response = answer
            chunks = split_discord_message(full_response, max_length=1900)
            await self._safe_send_response(interaction, chunks)

        except Exception as e:
            await self._safe_send_response(
                interaction,
                [f"⚠️ **Đã xảy ra lỗi:** `{e}`"]
            )
        finally:
            self.current_user = None
            if image_path and os.path.exists(image_path):
                try:
                    os.remove(image_path)
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(GeminiCog(bot))
