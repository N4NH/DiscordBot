import os
from typing import Optional, Tuple
import io
from PIL import Image
import aiohttp
import discord
from discord import app_commands

POSTERS_DIR = "posters"

def sanitize_filename(name: str) -> str:
    """Loại bỏ ký tự cấm trong tên file trên Windows"""
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in (" ", "-", "_", "(", ")")).strip()
    return cleaned.replace(" ", "_")[:50]

def save_poster_file(movie_id: int, name: str, image_bytes: bytes) -> str:
    """Lưu file ảnh poster trực quan vào thư mục posters/ trên máy tính"""
    os.makedirs(POSTERS_DIR, exist_ok=True)
    # Xóa file cũ của movie_id nếu có để tránh trùng lặp
    for fname in os.listdir(POSTERS_DIR):
        if fname.startswith(f"{movie_id}_") or fname == f"{movie_id}.jpg":
            try:
                os.remove(os.path.join(POSTERS_DIR, fname))
            except Exception:
                pass

    safe_name = sanitize_filename(name)
    filename = f"{movie_id}_{safe_name}.jpg" if safe_name else f"{movie_id}.jpg"
    filepath = os.path.join(POSTERS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(image_bytes)
    return filepath

def delete_poster_file(movie_id: int):
    """Xóa file ảnh poster trong thư mục posters/ khi xóa phim"""
    if not os.path.exists(POSTERS_DIR):
        return
    for fname in os.listdir(POSTERS_DIR):
        if fname.startswith(f"{movie_id}_") or fname == f"{movie_id}.jpg":
            try:
                os.remove(os.path.join(POSTERS_DIR, fname))
            except Exception:
                pass

def load_poster_bytes(movie: dict) -> Optional[bytes]:
    """Đọc ảnh poster từ thư mục posters/ trên máy tính hoặc fallback từ database"""
    movie_id = movie.get("id")
    if movie_id and os.path.exists(POSTERS_DIR):
        for fname in os.listdir(POSTERS_DIR):
            if fname.startswith(f"{movie_id}_") or fname == f"{movie_id}.jpg":
                try:
                    with open(os.path.join(POSTERS_DIR, fname), "rb") as f:
                        return f.read()
                except Exception:
                    pass

    return movie.get("image_data")

def compress_image_bytes(raw_bytes: bytes, max_dim: int = 600, quality: int = 75) -> bytes:
    """
    Nén ảnh về độ phân giải tối đa (mặc định 600px) và lưu định dạng JPEG chất lượng 75% tối ưu.
    Giảm kích thước file từ vài MB xuống còn ~30-50KB để lưu trực tiếp vào SQLite.
    """
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "RGBA":
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[3])
            img = background
        else:
            img = img.convert("RGB")

        width, height = img.size
        if width > max_dim or height > max_dim:
            ratio = min(max_dim / width, max_dim / height)
            new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        out_buf = io.BytesIO()
        img.save(out_buf, format="JPEG", quality=quality, optimize=True)
        return out_buf.getvalue()
    except Exception as e:
        print(f"[Compress Error]: {e}")
        return raw_bytes

async def process_and_compress_image(
    attachment: Optional[discord.Attachment] = None,
    url: Optional[str] = None
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Tải và nén ảnh về dạng bytes siêu nhẹ để lưu vào database SQLite:
    - Nếu có attachment (tải từ thiết bị): Đọc bytes và nén.
    - Nếu có url (link ảnh web): Tải về và nén.
    - Trả về (compressed_bytes, fallback_url)
    """
    raw_bytes = None
    fallback_url = None

    if attachment:
        try:
            raw_bytes = await attachment.read()
            fallback_url = attachment.url
        except Exception as e:
            print(f"[Attachment Error]: {e}")
    elif url:
        clean_url = url.strip()
        fallback_url = clean_url
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(clean_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        raw_bytes = await resp.read()
        except Exception as e:
            print(f"[URL Download Error]: {e}")

    if raw_bytes:
        compressed = compress_image_bytes(raw_bytes)
        return compressed, fallback_url
    return None, fallback_url

async def upload_to_catbox(file_bytes: bytes, filename: str = "image.png") -> Optional[str]:
    """Tải ảnh lên Catbox.moe để lấy link lưu trữ vĩnh viễn miễn phí (dự phòng)"""
    try:
        async with aiohttp.ClientSession() as session:
            data = aiohttp.FormData()
            data.add_field("reqtype", "fileupload")
            data.add_field("fileToUpload", file_bytes, filename=filename)
            async with session.post(
                "https://catbox.moe/user/api.php",
                data=data,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    result = (await resp.text()).strip()
                    if result.startswith("http"):
                        return result
    except Exception as e:
        print(f"[Catbox Upload Error]: {e}")
    return None

async def get_permanent_image_url(
    attachment: Optional[discord.Attachment] = None,
    url: Optional[str] = None
) -> Optional[str]:
    """Chuyển đổi file ảnh thành link dự phòng nếu cần"""
    if attachment:
        try:
            file_bytes = await attachment.read()
            permanent_url = await upload_to_catbox(file_bytes, filename=attachment.filename or "poster.png")
            if permanent_url:
                return permanent_url
        except Exception:
            pass
        return attachment.url

    if url:
        return url.strip()

    return None



def format_star_rating(score: float) -> str:
    """Tạo hiển thị sao trực quan (vd: ⭐⭐⭐⭐☆ 4.5/5.0)"""
    full_stars = int(score)
    has_half = (score - full_stars) >= 0.5
    empty_stars = 5 - full_stars - (1 if has_half else 0)
    stars_str = ("★" * full_stars) + ("½" if has_half else "") + ("☆" * max(0, empty_stars))
    return f"`{stars_str}` **{score:.1f}/5.0**"

def get_reviewer_rank(total_rated: int) -> str:
    """Hệ thống danh hiệu dựa theo số lượng phim đã đánh giá trong server"""
    if total_rated >= 20:
        return "👑 Bậc Thầy Điện Ảnh"
    elif total_rated >= 10:
        return "🎩 Nhà Phê Bình Cao Cấp"
    elif total_rated >= 6:
        return "📽️ Mọt Phim Chính Hiệu"
    elif total_rated >= 3:
        return "🍿 Tín Đồ Bỏng Ngô"
    elif total_rated >= 1:
        return "🎟️ Khán Giả Tập Sự"
    else:
        return "💤 Khán Giả Dạo Chơi"

def get_reviewer_vibe(avg_score: float, total_rated: int) -> str:
    """Phong cách thẩm phim dựa trên điểm trung bình đã chấm"""
    if total_rated == 0:
        return "Chưa có đánh giá nào"
    if avg_score >= 4.3:
        return "🥰 Dễ tính (Yêu điện ảnh, bao dung)"
    elif avg_score >= 3.3:
        return "⚖️ Công tâm (Chuẩn mực, khen chê rõ ràng)"
    else:
        return "🧐 Khó tính (Kén chọn, chuẩn mực Oscar)"

async def movie_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    import database
    if not interaction.guild_id:
        return []
    movies = database.search_movies(guild_id=interaction.guild_id, query=current, limit=25)
    return [app_commands.Choice(name=m, value=m) for m in movies]

def create_showcase_embed_page1(movie: dict) -> discord.Embed:
    """Tạo embed poster phim cho kênh chi tiết (Trang 1: Thông tin phim)"""
    avg_score = movie.get("avg_score", 0.0)
    total_votes = movie.get("total_votes", 0)
    
    score_text = (
        f"{format_star_rating(avg_score)} *(Tổng `{total_votes}` người đánh giá)*"
        if total_votes > 0
        else "*Chưa có đánh giá nào*"
    )
    
    embed = discord.Embed(
        title=f"🎬 {movie['name']}",
        description=(
            f"⭐ **Điểm số :** {score_text}\n"
            f"👤 **Người thêm :** `{movie.get('created_by', 'Ẩn danh')}`\n\n"
            f"💡 *Gõ `/rate {movie['name']}` để tham gia chấm điểm phim này!*"
        ),
        color=discord.Color.gold() if total_votes > 0 else discord.Color.blue()
    )
    img_bytes = load_poster_bytes(movie)
    if img_bytes:
        embed.set_image(url="attachment://poster.jpg")
    elif movie.get("image_url"):
        embed.set_image(url=movie["image_url"])
    embed.set_footer(text="Trang 1/2 • Hệ thống Giới Thiệu & Bảng Xếp Hạng Phim")
    return embed

def create_showcase_embed_page2(movie: dict) -> discord.Embed:
    """Tạo embed nhật ký đánh giá cho kênh chi tiết (Trang 2: 10 người đánh giá gần nhất)"""
    import database
    from datetime import datetime, timezone
    
    movie_id = movie.get("id")
    recent_ratings = database.get_recent_ratings_for_movie(movie_id, limit=10) if movie_id else []
    
    avg_score = movie.get("avg_score", 0.0)
    total_votes = movie.get("total_votes", 0)
    
    embed = discord.Embed(
        title=f"🎬 {movie['name']} • 10 Đánh Giá Gần Nhất",
        color=discord.Color.gold() if total_votes > 0 else discord.Color.blue()
    )
    
    score_header = (
        f"⭐ **Điểm số :** {format_star_rating(avg_score)} *(Tổng `{total_votes}` người đánh giá)*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    if not recent_ratings:
        embed.description = (
            f"{score_header}\n"
            f"📭 **Chưa có thành viên nào đánh giá bộ phim này.**\n\n"
            f"👉 Hãy là người đầu tiên chấm điểm với lệnh: `/rate {movie['name']}` !"
        )
    else:
        lines = [score_header, "👥 **Những người đánh giá gần đây nhất:**\n"]
        for idx, r in enumerate(recent_ratings, start=1):
            user_mention = f"<@{r['user_id']}>" if r.get('user_id') else f"`{r.get('user_name', 'Ẩn danh')}`"
            score_val = r.get("score", 0.0)
            star_display = format_star_rating(score_val)
            
            # Format thời gian tương đối Discord syntax <t:unix:R>
            time_str = ""
            if r.get("updated_at"):
                try:
                    dt = datetime.strptime(r["updated_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    time_str = f" • <t:{int(dt.timestamp())}:R>"
                except Exception:
                    time_str = ""
            
            lines.append(f"`#{idx:02d}` {user_mention} — {star_display}{time_str}")
            
        lines.append(f"\n💡 *Gõ `/rate {movie['name']}` để tham gia hoặc cập nhật điểm của bạn!*")
        embed.description = "\n".join(lines)
        
    img_bytes = load_poster_bytes(movie)
    if img_bytes:
        embed.set_thumbnail(url="attachment://thumb.jpg")
    elif movie.get("image_url"):
        embed.set_thumbnail(url=movie["image_url"])
        
    embed.set_footer(text="Trang 2/2 • Hệ thống Giới Thiệu & Bảng Xếp Hạng Phim")
    return embed

def create_showcase_embed(movie: dict) -> discord.Embed:
    """Tương thích ngược: mặc định trả về Trang 1"""
    return create_showcase_embed_page1(movie)

def get_movie_from_interaction(interaction: discord.Interaction) -> Optional[dict]:
    """Tìm thông tin phim từ tương tác nút bấm của tin nhắn showcase"""
    import database
    if not interaction.guild_id:
        return None
        
    # 1. Tra cứu theo message.id
    if interaction.message:
        movie = database.get_movie_by_showcase_message_id(interaction.guild_id, interaction.message.id)
        if movie:
            return movie
            
    # 2. Dự phòng: Tra cứu từ tiêu đề embed
    if interaction.message and interaction.message.embeds:
        title = interaction.message.embeds[0].title or ""
        clean_name = title.replace("🎬", "").split("•")[0].strip()
        if clean_name:
            movie = database.get_movie(interaction.guild_id, clean_name)
            if movie and interaction.message.id and not movie.get("showcase_message_id"):
                database.set_movie_showcase_message_id(movie["id"], interaction.message.id)
            return movie
    return None

class MovieShowcaseView(discord.ui.View):
    """View cho kênh chi tiết phim (chỉ người bấm nút mới thấy 10 đánh giá - ephemeral tránh làm loạn kênh)"""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Xem 10 đánh giá gần nhất",
        style=discord.ButtonStyle.secondary,
        custom_id="showcase_btn_page2",
        emoji="👥"
    )
    async def btn_page2(self, interaction: discord.Interaction, button: discord.ui.Button):
        movie = get_movie_from_interaction(interaction)
        if not movie:
            await interaction.response.send_message("❌ Không tìm thấy thông tin phim!", ephemeral=True)
            return
        embed = create_showcase_embed_page2(movie)
        img_bytes = load_poster_bytes(movie)
        file = discord.File(io.BytesIO(img_bytes), filename="thumb.jpg") if img_bytes else None
        # Chỉ hiển thị cho riêng người dùng bấm nút (ephemeral=True), tránh làm thay đổi bài đăng chung
        if file:
            await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Thông tin chính",
        style=discord.ButtonStyle.primary,
        custom_id="showcase_btn_page1",
        emoji="🎬"
    )
    async def btn_page1(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Nút hỗ trợ tương thích ngược nếu còn bài cũ
        await interaction.response.send_message(
            "📌 Đây là bài đăng chính của bộ phim. Bấm nút **Xem 10 đánh giá gần nhất** để xem riêng cho bạn nhé!",
            ephemeral=True
        )

async def update_showcase_message(bot, guild_id: int, movie_data: dict, new_image: bool = False):
    """Cập nhật embed phim trong kênh chi tiết theo thời gian thực kèm nút xem đánh giá riêng"""
    import database
    channel_id = database.get_showcase_channel(guild_id)
    msg_id = movie_data.get("showcase_message_id")
    if not channel_id or not msg_id:
        return
    try:
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        if not channel:
            return
        msg = await channel.fetch_message(msg_id)
        embed = create_showcase_embed_page1(movie_data)
        img_bytes = load_poster_bytes(movie_data)
        if new_image and img_bytes:
            file = discord.File(io.BytesIO(img_bytes), filename="poster.jpg")
            await msg.edit(embed=embed, attachments=[file], view=MovieShowcaseView())
        else:
            await msg.edit(embed=embed, view=MovieShowcaseView())
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


