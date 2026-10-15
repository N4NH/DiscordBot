import asyncio
import os
import re
from typing import List, Optional, Set, Tuple
import discord
from discord import app_commands
from discord.ext import commands
from openai import AsyncOpenAI

# Cấu hình mặc định cho API AI
DEFAULT_BASE_URL = os.getenv("AI_BASE_URL", "https://api.vilao.ai/v1")
DEFAULT_API_KEY = os.getenv("AI_API_KEY", "")
DEFAULT_ALLOWED_USERS: Set[str] = set()

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_FILE = os.path.join(ROOT_DIR, "model.txt")
DEFAULT_MODEL = "cd/gpt-6-astra"


def get_active_model() -> str:
    """Đọc tên model trực tiếp từ file model.txt. Nếu không tìm thấy thì đọc từ .env."""
    if os.path.exists(MODEL_FILE):
        try:
            with open(MODEL_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
        except Exception:
            pass
    return os.getenv("AI_MODEL", DEFAULT_MODEL).strip()


def get_allowed_users() -> Set[str]:
    """Lấy danh sách các username hoặc user ID được phép sử dụng AI."""
    users = set(DEFAULT_ALLOWED_USERS)
    env_users = os.getenv("ALLOWED_AI_USERS", "")
    if env_users:
        for u in env_users.split(","):
            u_clean = u.strip().lower()
            if u_clean:
                users.add(u_clean)
    return users


def is_user_authorized(user: discord.User | discord.Member) -> bool:
    """Kiểm tra xem người dùng có quyền gọi lệnh AI hay không."""
    allowed = get_allowed_users()
    username = (user.name or "").lower().strip()
    user_id = str(user.id).strip()
    global_name = (user.global_name or "").lower().strip()

    return (
        username in allowed
        or user_id in allowed
        or global_name in allowed
    )


def remove_accents(input_str: str) -> str:
    """Loại bỏ dấu tiếng Việt để đối sánh linh hoạt."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", input_str)
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).replace("đ", "d").replace("Đ", "D")


def should_search_web(query: str) -> bool:
    """Tự động phát hiện xem câu hỏi có cần tra cứu thông tin thời gian thực từ Google/Internet hay không (hỗ trợ cả có dấu và không dấu)."""
    q_raw = query.lower()
    q_no_accent = remove_accents(q_raw)

    keywords = [
        "ai là", "là ai", "thằng này là ai", "con này là ai", "ông này là ai",
        "bà này là ai", "người này là ai", "ai đấy", "ai thế", "thằng nào",
        "con nào", "ai đây", "là gì", "là cái gì", "tra cứu", "tìm kiếm",
        "tìm giúp", "tìm hiểu", "tra gg", "tra google", "search", "tin tức",
        "mới nhất", "hôm nay", "ngày nay", "năm nay", "dạo này", "gần đây",
        "thời sự", "thời tiết", "giá cả", "bóng đá", "kết quả", "tỉ số",
        "lịch thi đấu", "ở đâu", "bao nhiêu", "khi nào", "thông tin về",
        "tiểu sử", "sự nghiệp", "phốt", "drama", "scandal", "2024", "2025", "2026",
        # Không dấu
        "la ai", "ai la", "thang nay la ai", "ong nay la ai", "ba nay la ai",
        "nguoi nay la ai", "ai the", "ai day", "la gi", "la cai gi", "tra cuu",
        "tim kiem", "tin tuc", "moi nhat", "hom nay", "nam nay", "gan day"
    ]
    return any(kw in q_raw or kw in q_no_accent for kw in keywords)


def search_ddg_multibackend(query: str, max_results: int = 3) -> List[dict]:
    """Tìm kiếm DuckDuckGo lần lượt qua các backend html, lite và api để tránh lỗi No results found."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []

    # Thử qua các backend: html và lite rất ổn định với tiếng Việt
    for backend in ["html", "lite", "api"]:
        try:
            with DDGS(timeout=5) as d:
                res = list(d.text(query, backend=backend, max_results=max_results))
                if res:
                    return res
        except Exception:
            continue
    return []


def search_wikipedia_fallback(query: str, max_results: int = 2) -> List[dict]:
    """Tìm kiếm dự phòng qua Wikipedia API tiếng Việt (chuyên dùng khi hỏi về nhân vật, sự kiện, tiểu sử)."""
    import urllib.request
    import urllib.parse
    import json
    import re

    try:
        url = (
            f"https://vi.wikipedia.org/w/api.php?action=query&list=search"
            f"&srsearch={urllib.parse.quote(query)}&format=json&utf8=1"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("query", {}).get("search", [])
            results = []
            for item in items[:max_results]:
                title = item.get("title", "")
                snippet_html = item.get("snippet", "")
                snippet = re.sub(r"<[^>]+>", "", snippet_html).strip()
                page_url = f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                results.append({
                    "title": f"{title} (Wikipedia)",
                    "body": snippet,
                    "href": page_url
                })
            return results
    except Exception:
        return []


def sync_multi_search(query: str, max_results: int = 3) -> List[dict]:
    """Tìm kiếm tổng hợp: DuckDuckGo -> Wikipedia."""
    # 1. Thử DuckDuckGo HTML / Lite
    res = search_ddg_multibackend(query, max_results=max_results)
    if res:
        return res

    # 2. Dự phòng bằng Wikipedia nếu DuckDuckGo không tìm thấy kết quả
    wiki_res = search_wikipedia_fallback(query, max_results=max_results)
    if wiki_res:
        return wiki_res

    return []


async def perform_web_search(query: str, max_results: int = 3) -> List[dict]:
    """Tìm kiếm trực tuyến không đồng bộ (chạy trên thread riêng để không chặn Discord bot)."""
    clean_query = query.strip()
    prefixes = [
        "cho hỏi", "hỏi xíu", "cho tui hỏi", "bạn ơi", "ê bot",
        "bot ơi", "tra gg", "tra google", "tìm kiếm", "tìm cho tôi", "tra cứu"
    ]
    for prefix in prefixes:
        if clean_query.lower().startswith(prefix):
            clean_query = clean_query[len(prefix):].strip()

    if not clean_query:
        clean_query = query

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(sync_multi_search, clean_query, max_results),
            timeout=8.0
        )
        return results or []
    except Exception:
        return []


def split_text_into_chunks(text: str, max_chunk_size: int = 1900) -> List[str]:
    """Tách văn bản dài thành các đoạn nhỏ dưới 2000 ký tự để gửi trên Discord."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    lines = text.splitlines(keepends=True)
    current_chunk = ""

    for line in lines:
        if len(current_chunk) + len(line) <= max_chunk_size:
            current_chunk += line
        else:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""

            while len(line) > max_chunk_size:
                chunks.append(line[:max_chunk_size])
                line = line[max_chunk_size:]
            current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class GptCog(commands.Cog, name="GPT"):
    """Cog tích hợp trợ lí ảo AI với lệnh /gpt và hỗ trợ tra cứu trực tuyến."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.base_url = os.getenv("AI_BASE_URL", DEFAULT_BASE_URL)
        self.api_key = os.getenv("AI_API_KEY", DEFAULT_API_KEY)
        self.client = AsyncOpenAI(base_url=self.base_url, api_key=self.api_key)

    def get_bot_nickname(self, guild: Optional[discord.Guild]) -> str:
        """Lấy biệt danh của bot trong server (hoặc tên mặc định nếu không có)."""
        if guild and guild.me and guild.me.display_name:
            return guild.me.display_name
        if self.bot.user and self.bot.user.display_name:
            return self.bot.user.display_name
        return "Bánh Gấu"

    async def generate_ai_response(
        self,
        prompt: str,
        bot_name: str,
        guild_name: str,
        web_search_enabled: Optional[bool] = None
    ) -> Tuple[str, List[dict]]:
        """Gửi prompt đến API Vilao AI với model chỉ định trong model.txt kèm dữ liệu tra cứu trực tuyến."""
        active_model = get_active_model()

        # Kiểm tra xem có cần tra cứu trực tuyến không
        do_search = web_search_enabled if web_search_enabled is not None else should_search_web(prompt)
        search_results: List[dict] = []

        if do_search:
            search_results = await perform_web_search(prompt, max_results=3)

        # Tạo prompt đầu vào cho AI: nếu có kết quả tra cứu trực tuyến thì đính kèm vào
        enriched_user_prompt = prompt
        if search_results:
            snippets = []
            for idx, item in enumerate(search_results, start=1):
                t = item.get("title", "Không có tiêu đề")
                b = item.get("body", "")
                b_clean = (b[:500].strip() + "...") if len(b) > 500 else b.strip()
                snippets.append(f"[{idx}] {t}\n{b_clean}")
            
            search_context = "\n\n".join(snippets)
            enriched_user_prompt = (
                f"=== DỮ LIỆU TRA CỨU TRỰC TUYẾN MỚI NHẤT TỪ GOOGLE/INTERNET ===\n"
                f"{search_context}\n"
                f"===============================================================\n"
                f"Dựa vào thông tin tra cứu trực tuyến cập nhật ở trên (kết hợp với kiến thức sẵn có của bạn), "
                f"hãy giải đáp câu hỏi sau của người dùng một cách chính xác, tự nhiên theo đúng phong cách trợ lí:\n"
                f"{prompt}"
            )

        # Prompt gốc theo đúng yêu cầu: Tui là trợ lí ảo "Tên theo biệt danh của sever discord đó" ...
        if guild_name:
            system_content = (
                f'Tui là trợ lí ảo "{bot_name}" của server discord "{guild_name}". '
                f'Hãy trả lời câu hỏi của người dùng một cách thông minh, chuẩn xác, hữu ích, '
                f'tự nhiên, thân thiện và hài hước bằng tiếng Việt. Xưng hô thân mật phù hợp với môi trường Discord.'
            )
        else:
            system_content = (
                f'Tui là trợ lí ảo "{bot_name}". '
                f'Hãy trả lời câu hỏi của người dùng qua tin nhắn riêng (DM) một cách thông minh, chuẩn xác, hữu ích, '
                f'tự nhiên, thân thiện và hài hước bằng tiếng Việt. Xưng hô thân mật phù hợp với môi trường Discord.'
            )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": enriched_user_prompt}
        ]

        response = await self.client.chat.completions.create(
            model=active_model,
            messages=messages,
            temperature=0.7,
        )
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip(), search_results

        raise RuntimeError(f"Model {active_model} không trả về nội dung nào.")

    @app_commands.command(name="gpt", description="Hỏi đáp với trợ lí ảo AI (có hỗ trợ tra cứu trực tuyến, dùng được cả trong DM)")
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.describe(
        cau_hoi="Nội dung hoặc câu hỏi bạn muốn hỏi trợ lí ảo",
        tra_cuu="Bật/Tắt tra cứu trực tuyến trên Internet (Mặc định: Tự động tra cứu khi hỏi người/sự kiện mới)"
    )
    async def cmd_gpt(
        self,
        interaction: discord.Interaction,
        cau_hoi: str,
        tra_cuu: Optional[bool] = None
    ):
        """Slash command /gpt <câu_hỏi> [tra_cuu]."""
        # 1. Kiểm tra quyền hạn của người dùng
        if not is_user_authorized(interaction.user):
            await interaction.response.send_message(
                "🚫 **Từ chối truy cập!**\nBạn không nằm trong danh sách được phép sử dụng tính năng AI này.",
                ephemeral=True
            )
            return

        # 2. Defer tương tác vì AI và tìm kiếm cần thời gian xử lý
        await interaction.response.defer(thinking=True)

        bot_name = self.get_bot_nickname(interaction.guild)
        guild_name = interaction.guild.name if interaction.guild else None

        try:
            # 3. Gọi AI
            reply, search_results = await self.generate_ai_response(
                prompt=cau_hoi,
                bot_name=bot_name,
                guild_name=guild_name,
                web_search_enabled=tra_cuu
            )

            # 4. Trình bày kết quả gửi về cho người dùng
            header = f"> 💬 **{interaction.user.display_name}** hỏi: *{cau_hoi}*\n\n"
            full_response = header + reply

            # Nếu có nguồn tra cứu trực tuyến, thêm link trích dẫn ở cuối
            if search_results:
                sources = []
                for item in search_results[:3]:
                    t = item.get("title", "Nguồn tra cứu")
                    u = item.get("href", "")
                    if u:
                        short_title = (t[:35] + "..") if len(t) > 35 else t
                        sources.append(f"[{short_title}]({u})")
                if sources:
                    full_response += f"\n\n🌐 *Nguồn tra cứu trực tuyến:* {' • '.join(sources)}"

            chunks = split_text_into_chunks(full_response, max_chunk_size=1900)

            # Gửi tin nhắn đầu tiên qua followup
            await interaction.followup.send(chunks[0])

            # Nếu nội dung dài hơn 2000 ký tự, gửi tiếp các đoạn còn lại
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk)

        except Exception as e:
            await interaction.followup.send(
                f"⚠️ **Đã xảy ra lỗi khi xử lý câu hỏi:** `{e}`\nVui lòng thử lại sau giây lát!"
            )

    @commands.command(name="gpt", aliases=["GPT"], help="Hỏi đáp với trợ lí ảo AI (tự động tra cứu trực tuyến)")
    async def prefix_gpt(self, ctx: commands.Context, *, cau_hoi: str):
        """Prefix command !gpt <câu_hỏi> hoặc !GPT <câu_hỏi>."""
        if not is_user_authorized(ctx.author):
            await ctx.reply(
                "🚫 **Từ chối truy cập!** Bạn không có quyền sử dụng lệnh AI này.",
                mention_author=False
            )
            return

        bot_name = self.get_bot_nickname(ctx.guild)
        guild_name = ctx.guild.name if ctx.guild else None

        async with ctx.typing():
            try:
                reply, search_results = await self.generate_ai_response(
                    prompt=cau_hoi,
                    bot_name=bot_name,
                    guild_name=guild_name,
                    web_search_enabled=None
                )
                header = f"> 💬 **{ctx.author.display_name}** hỏi: *{cau_hoi}*\n\n"
                full_response = header + reply

                if search_results:
                    sources = []
                    for item in search_results[:3]:
                        t = item.get("title", "Nguồn tra cứu")
                        u = item.get("href", "")
                        if u:
                            short_title = (t[:35] + "..") if len(t) > 35 else t
                            sources.append(f"[{short_title}]({u})")
                    if sources:
                        full_response += f"\n\n🌐 *Nguồn tra cứu trực tuyến:* {' • '.join(sources)}"

                chunks = split_text_into_chunks(full_response, max_chunk_size=1900)
                await ctx.reply(chunks[0], mention_author=False)
                for chunk in chunks[1:]:
                    await ctx.send(chunk)
            except Exception as e:
                await ctx.reply(f"⚠️ **Lỗi:** `{e}`", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(GptCog(bot))
