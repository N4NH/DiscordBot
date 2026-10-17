import asyncio
import os
import re
import json
import random
import urllib.request
from typing import Optional, List, Dict, Any, Literal, Tuple
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp

# Cấu hình yt-dlp tối ưu cho phát nhạc trực tiếp & vượt tường bot detection
YTDL_BASE_OPTIONS: Dict[str, Any] = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'extract_flat': False,
    'extractor_args': {
        'youtube': {
            'player_client': ['ios', 'android'],
        }
    }
}

# Tự động nạp cookies.txt nếu có trong thư mục gốc
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_FILE = os.path.join(ROOT_DIR, "cookies.txt")
if os.path.exists(COOKIE_FILE):
    YTDL_BASE_OPTIONS['cookiefile'] = COOKIE_FILE
elif os.path.exists("cookies.txt"):
    YTDL_BASE_OPTIONS['cookiefile'] = "cookies.txt"

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -ar 48000 -ac 2 -b:a 320k'
}

def format_duration(seconds: Optional[int]) -> str:
    """Định dạng giây thành chuỗi MM:SS hoặc HH:MM:SS."""
    if not seconds or seconds <= 0:
        return "Live / Không rõ"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

class Song:
    """Đại diện cho một bài hát trong hàng chờ."""
    def __init__(
        self,
        title: str,
        webpage_url: str,
        stream_url: str,
        duration: int,
        uploader: str,
        thumbnail: str,
        platform: str,
        requester: discord.Member,
    ):
        self.title = title
        self.webpage_url = webpage_url
        self.stream_url = stream_url
        self.duration = duration
        self.uploader = uploader or "Không rõ"
        self.thumbnail = thumbnail
        self.platform = platform  # "YouTube" hoặc "SoundCloud"
        self.requester = requester

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)

    @property
    def platform_emoji(self) -> str:
        if self.platform == "Spotify":
            return "🟢"
        elif self.platform == "SoundCloud":
            return "🟠"
        return "🔴"

    @property
    def platform_color(self) -> discord.Color:
        if self.platform == "Spotify":
            return discord.Color.from_rgb(30, 215, 96)  # Spotify Green #1ED760
        elif self.platform == "SoundCloud":
            return discord.Color.from_rgb(255, 85, 0)
        return discord.Color.from_rgb(255, 0, 0)

    async def get_audio_source(self, volume: float = 1.0) -> discord.PCMVolumeTransformer:
        """Tạo nguồn âm thanh FFmpeg với volume control và tự động resolve link stream khi phát."""
        stream = self.stream_url
        if not stream or "spotify.com" in stream or "soundcloud.com" in stream or "youtube.com" in stream or "youtu.be" in stream:
            loop = asyncio.get_running_loop()
            if self.platform == "Spotify":
                # Spotify Bridge: Tìm kiếm stream audio chất lượng cao nhất tương ứng
                search_q = f"ytsearch1:{self.title} {self.uploader} audio"
                info = await loop.run_in_executor(None, lambda: SongExtractor.extract_raw(search_q))
                if info and "entries" in info and info["entries"]:
                    stream = info["entries"][0].get("url")
                    self.stream_url = stream
                elif info and "url" in info:
                    stream = info.get("url")
                    self.stream_url = stream
            else:
                info = await loop.run_in_executor(None, lambda: SongExtractor.extract_raw(self.webpage_url))
                if info:
                    stream = info.get('url')
                    self.stream_url = stream
                    if info.get('title'):
                        self.title = info.get('title')
                    if info.get('duration'):
                        self.duration = int(info.get('duration'))
                    if info.get('thumbnail'):
                        self.thumbnail = info.get('thumbnail')
                    if info.get('uploader') or info.get('channel'):
                        self.uploader = info.get('uploader') or info.get('channel')

        source = discord.FFmpegPCMAudio(stream, **FFMPEG_OPTIONS)
        return discord.PCMVolumeTransformer(source, volume=volume)


class SpotifyHelper:
    """Bóc tách siêu dữ liệu bài hát, album và playlist từ Spotify thông qua embed API."""

    @staticmethod
    def is_spotify_url(url: str) -> bool:
        lowered = url.lower()
        return "open.spotify.com" in lowered or "spotify:" in lowered

    @classmethod
    def extract_spotify_data(cls, url: str) -> Optional[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
        clean_url = url.split("?")[0]
        match = re.search(r"open\.spotify\.com/(track|playlist|album)/([a-zA-Z0-9]+)", clean_url)
        if not match:
            uri_match = re.search(r"spotify:(track|playlist|album):([a-zA-Z0-9]+)", clean_url)
            if uri_match:
                entity_type = uri_match.group(1)
                entity_id = uri_match.group(2)
            else:
                return None
        else:
            entity_type = match.group(1)
            entity_id = match.group(2)

        embed_url = f"https://open.spotify.com/embed/{entity_type}/{entity_id}"
        req = urllib.request.Request(embed_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8")
        except Exception as e:
            print(f"[SpotifyHelper Error] {e}", flush=True)
            return None

        script_match = re.search(r'id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html)
        if not script_match:
            return None

        try:
            data = json.loads(script_match.group(1))
            entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        except Exception:
            return None

        # Lấy ảnh bìa
        cover = ""
        visual_identity = entity.get("visualIdentity", {})
        if visual_identity and "image" in visual_identity and visual_identity["image"]:
            cover = visual_identity["image"][-1].get("url", "")
        elif "coverArt" in entity and entity["coverArt"] and "sources" in entity["coverArt"]:
            sources = entity["coverArt"]["sources"]
            if sources:
                cover = sources[-1].get("url", "")

        tracks: List[Dict[str, Any]] = []
        if entity_type == "track":
            title = entity.get("title") or entity.get("name") or "Spotify Track"
            artist_list = [a.get("name") for a in entity.get("artists", []) if a.get("name")]
            artist = ", ".join(artist_list) if artist_list else (entity.get("subtitle") or "Spotify Artist")
            duration = int((entity.get("duration") or 0) / 1000)

            tracks.append({
                "title": title,
                "artist": artist,
                "duration": duration,
                "thumbnail": cover,
                "url": f"https://open.spotify.com/track/{entity_id}"
            })
        else:
            track_list = entity.get("trackList", [])
            for t in track_list:
                t_title = t.get("title") or "Spotify Track"
                t_artist = t.get("subtitle") or "Spotify Artist"
                t_duration = int((t.get("duration") or 0) / 1000)
                t_uri = t.get("uri", "")
                t_id = t_uri.split(":")[-1] if ":" in t_uri else ""
                t_url = f"https://open.spotify.com/track/{t_id}" if t_id else f"https://open.spotify.com/{entity_type}/{entity_id}"

                tracks.append({
                    "title": t_title,
                    "artist": t_artist,
                    "duration": t_duration,
                    "thumbnail": cover,
                    "url": t_url
                })

        info = {
            "title": entity.get("title") or entity.get("name") or ("Spotify Track" if entity_type == "track" else "Spotify Playlist"),
            "thumbnail": cover,
            "type": entity_type
        }
        return (entity_type, info, tracks)


class SongExtractor:
    """Trích xuất metadata và luồng âm thanh từ YouTube, SoundCloud và Spotify."""
    
    @staticmethod
    def is_url(query: str) -> bool:
        parsed = urlparse(query)
        return bool(parsed.scheme and parsed.netloc)

    @staticmethod
    def detect_platform(query: str) -> str:
        lowered = query.lower()
        if "spotify.com" in lowered or "spotify:" in lowered:
            return "Spotify"
        elif "soundcloud.com" in lowered or "on.soundcloud.com" in lowered:
            return "SoundCloud"
        return "YouTube"

    @staticmethod
    def extract_raw(query: str, download: bool = False) -> Optional[Dict[str, Any]]:
        with yt_dlp.YoutubeDL(YTDL_BASE_OPTIONS) as ydl:
            try:
                return ydl.extract_info(query, download=download)
            except Exception as e:
                print(f"[SongExtractor Error] {e}", flush=True)
                return None

    @classmethod
    async def get_songs(
        cls,
        query: str,
        platform_preference: Optional[str] = None,
        requester: Optional[discord.Member] = None,
    ) -> List[Song]:
        loop = asyncio.get_running_loop()
        query = query.strip()

        # 1. Xử lý link Spotify trực tiếp (Bài hát, Playlist hoặc Album)
        if cls.is_url(query) and SpotifyHelper.is_spotify_url(query):
            sp_res = await loop.run_in_executor(None, lambda: SpotifyHelper.extract_spotify_data(query))
            if sp_res:
                _, _, sp_tracks = sp_res
                songs: List[Song] = []
                for t in sp_tracks:
                    songs.append(
                        Song(
                            title=t["title"],
                            webpage_url=t["url"],
                            stream_url="",  # Sẽ được Spotify Bridge resolve ngay khi phát
                            duration=t["duration"],
                            uploader=t["artist"],
                            thumbnail=t["thumbnail"],
                            platform="Spotify",
                            requester=requester,
                        )
                    )
                return songs

        # 2. Xác định query và platform nếu không phải link Spotify
        if cls.is_url(query):
            target_platform = cls.detect_platform(query)
            target_query = query
        else:
            if platform_preference == "SoundCloud":
                target_platform = "SoundCloud"
                target_query = f"scsearch1:{query}"
            elif platform_preference == "Spotify":
                target_platform = "Spotify"
                target_query = f"ytsearch1:{query} audio"
            else:
                target_platform = "YouTube"
                target_query = f"ytsearch1:{query}"

        # Trích xuất bất đồng bộ để không block luồng discord
        def _extract():
            opts = dict(YTDL_BASE_OPTIONS)
            if cls.is_url(query):
                opts['noplaylist'] = False
                opts['extract_flat'] = 'in_playlist'
            else:
                opts['noplaylist'] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(target_query, download=False)

        info = await loop.run_in_executor(None, _extract)
        if not info:
            return []

        # Xử lý nếu là danh sách phát (Playlist / Search entries)
        songs: List[Song] = []
        if 'entries' in info and info['entries']:
            for entry in info['entries']:
                if not entry:
                    continue
                webpage_url = entry.get('webpage_url') or entry.get('url') or query
                raw_title = entry.get('title')
                if not raw_title:
                    clean_slug = webpage_url.rstrip('/').split('/')[-1].split('?')[0].replace('-', ' ')
                    title = clean_slug.title() if clean_slug else "Bài hát trong danh sách"
                else:
                    title = raw_title

                duration = int(entry.get('duration') or 0)
                uploader = entry.get('uploader') or entry.get('channel') or "Không rõ"
                thumbnail = entry.get('thumbnail') or (entry.get('thumbnails', [{}])[-1].get('url') if entry.get('thumbnails') else "")

                # Nếu là flat playlist, entry['url'] có thể là link webpage chứ chưa phải stream
                stream_url = entry.get('url')
                if stream_url and ("soundcloud.com" in stream_url or "youtube.com" in stream_url or "youtu.be" in stream_url):
                    stream_url = ""

                # Xác định platform từ extractor hoặc url
                ext = (entry.get('extractor') or "").lower()
                detected = "SoundCloud" if ("soundcloud" in ext or "soundcloud.com" in webpage_url) else target_platform

                songs.append(
                    Song(
                        title=title,
                        webpage_url=webpage_url,
                        stream_url=stream_url if stream_url and stream_url.startswith("http") else "",
                        duration=duration,
                        uploader=uploader,
                        thumbnail=thumbnail,
                        platform=detected,
                        requester=requester,
                    )
                )
        else:
            stream_url = info.get('url')
            title = info.get('title') or "Không có tiêu đề"
            webpage_url = info.get('webpage_url') or query
            duration = int(info.get('duration') or 0)
            uploader = info.get('uploader') or info.get('channel') or "Không rõ"
            thumbnail = info.get('thumbnail') or ""
            ext = (info.get('extractor') or "").lower()
            detected = "SoundCloud" if ("soundcloud" in ext or "soundcloud.com" in webpage_url) else target_platform

            songs.append(
                Song(
                    title=title,
                    webpage_url=webpage_url,
                    stream_url=stream_url if stream_url and stream_url.startswith("http") else "",
                    duration=duration,
                    uploader=uploader,
                    thumbnail=thumbnail,
                    platform=detected,
                    requester=requester,
                )
            )

        return songs


class VolumeModal(discord.ui.Modal, title="🔊 Điều Chỉnh Âm Lượng"):
    vol_input = discord.ui.TextInput(
        label="Nhập mức âm lượng (1 - 150%)",
        placeholder="Ví dụ: 80",
        min_length=1,
        max_length=3,
        required=True
    )

    def __init__(self, player: "GuildPlayer"):
        super().__init__()
        self.player = player
        self.vol_input.default = str(int(self.player.volume * 100))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.vol_input.value.strip())
            if not (1 <= val <= 150):
                await interaction.response.send_message("❌ Âm lượng phải nằm trong khoảng từ 1% đến 150%!", ephemeral=True)
                return
            await self.player.set_volume(val / 100.0)
            await interaction.response.send_message(f"🔊 Đã đổi âm lượng sang **{val}%**!", ephemeral=True)
            await self.player.update_player_message()
        except ValueError:
            await interaction.response.send_message("❌ Vui lòng nhập số hợp lệ!", ephemeral=True)


class MusicControlView(discord.ui.View):
    """Bảng điều khiển giao diện phím bấm trực quan chuẩn Jockey / SoundCloud."""
    def __init__(self, player: "GuildPlayer"):
        super().__init__(timeout=None)
        self.player = player
        self.sync_buttons()

    def sync_buttons(self):
        # Trạng thái Pause / Resume
        if self.player.is_paused:
            self.pause_resume_btn.emoji = "▶️"
            self.pause_resume_btn.label = "Tiếp tục"
            self.pause_resume_btn.style = discord.ButtonStyle.success
        else:
            self.pause_resume_btn.emoji = "⏸️"
            self.pause_resume_btn.label = "Tạm dừng"
            self.pause_resume_btn.style = discord.ButtonStyle.secondary

        # Trạng thái Loop
        if self.player.loop_mode == "song":
            self.loop_btn.label = "Lặp: 1 Bài"
            self.loop_btn.style = discord.ButtonStyle.success
        elif self.player.loop_mode == "queue":
            self.loop_btn.label = "Lặp: Toàn Bộ"
            self.loop_btn.style = discord.ButtonStyle.primary
        else:
            self.loop_btn.label = "Lặp: Tắt"
            self.loop_btn.style = discord.ButtonStyle.secondary

    async def check_user_voice(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn cần vào kênh đàm thoại (Voice Channel) để thao tác!", ephemeral=True)
            return False
        if self.player.voice_client and self.player.voice_client.channel != interaction.user.voice.channel:
            await interaction.response.send_message("❌ Bạn phải ở cùng kênh thoại với bot!", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="⏸️", label="Tạm dừng", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        if self.player.is_paused:
            self.player.resume()
            await interaction.response.send_message("▶️ Đã tiếp tục phát nhạc!", ephemeral=True)
        else:
            self.player.pause()
            await interaction.response.send_message("⏸️ Đã tạm dừng nhạc!", ephemeral=True)
        self.sync_buttons()
        await self.player.update_player_message()

    @discord.ui.button(emoji="⏭️", label="Bỏ qua", style=discord.ButtonStyle.secondary, row=0)
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        if not self.player.current:
            await interaction.response.send_message("❌ Không có bài hát nào đang phát!", ephemeral=True)
            return
        title = self.player.current.title
        self.player.skip()
        await interaction.response.send_message(f"⏭️ **{interaction.user.display_name}** đã bỏ qua: **{title}**!")

    @discord.ui.button(emoji="🔁", label="Lặp: Tắt", style=discord.ButtonStyle.secondary, row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        modes = ["off", "song", "queue"]
        next_mode = modes[(modes.index(self.player.loop_mode) + 1) % len(modes)]
        self.player.loop_mode = next_mode
        self.sync_buttons()
        
        mode_names = {"off": "Đã tắt lặp", "song": "Lặp lại bài hát hiện tại 🔂", "queue": "Lặp lại toàn bộ hàng chờ 🔁"}
        await interaction.response.send_message(f"🔁 Chế độ: **{mode_names[next_mode]}**", ephemeral=True)
        await self.player.update_player_message()

    @discord.ui.button(emoji="🔀", label="Trộn bài", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        if len(self.player.queue) < 2:
            await interaction.response.send_message("❌ Cần ít nhất 2 bài trong hàng chờ để trộn!", ephemeral=True)
            return
        self.player.shuffle()
        await interaction.response.send_message(f"🔀 **{interaction.user.display_name}** đã xáo trộn danh sách phát ({len(self.player.queue)} bài)!")
        await self.player.update_player_message()

    @discord.ui.button(emoji="⏹️", label="Dừng", style=discord.ButtonStyle.danger, row=0)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        await self.player.stop()
        await interaction.response.send_message(f"⏹️ **{interaction.user.display_name}** đã dừng phát nhạc và làm sạch hàng chờ!")

    @discord.ui.button(emoji="📜", label="Hàng chờ", style=discord.ButtonStyle.primary, row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = self.player.get_queue_embed(page=0)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(emoji="🔉", label="-10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_down_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        new_vol = max(0.1, round(self.player.volume - 0.1, 2))
        await self.player.set_volume(new_vol)
        await interaction.response.send_message(f"🔉 Đã giảm âm lượng xuống **{int(new_vol * 100)}%**", ephemeral=True)
        await self.player.update_player_message()

    @discord.ui.button(emoji="🔊", label="+10%", style=discord.ButtonStyle.secondary, row=1)
    async def vol_up_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        new_vol = min(1.5, round(self.player.volume + 0.1, 2))
        await self.player.set_volume(new_vol)
        await interaction.response.send_message(f"🔊 Đã tăng âm lượng lên **{int(new_vol * 100)}%**", ephemeral=True)
        await self.player.update_player_message()

    @discord.ui.button(emoji="🎚️", label="Chỉnh âm", style=discord.ButtonStyle.secondary, row=1)
    async def vol_modal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        await interaction.response.send_modal(VolumeModal(self.player))

    @discord.ui.button(emoji="🚪", label="Rời kênh", style=discord.ButtonStyle.danger, row=1)
    async def leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_user_voice(interaction):
            return
        await self.player.disconnect()
        await interaction.response.send_message("👋 Bot đã rời khỏi kênh đàm thoại!")


class QueuePaginationView(discord.ui.View):
    """Xem danh sách hàng chờ có chuyển trang."""
    def __init__(self, player: "GuildPlayer", author: discord.User, page: int = 0):
        super().__init__(timeout=60)
        self.player = player
        self.author = author
        self.current_page = page
        self.total_pages = max(1, (len(self.player.queue) + 9) // 10)
        self.update_buttons()

    def update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.page_indicator.label = f"{self.current_page + 1}/{self.total_pages}"
        self.next_btn.disabled = (self.current_page >= self.total_pages - 1)

    @discord.ui.button(emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Bạn không thể thao tác nút này!", ephemeral=True)
            return
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = self.player.get_queue_embed(page=self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="1/1", style=discord.ButtonStyle.primary, disabled=True)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(emoji="➡️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Bạn không thể thao tác nút này!", ephemeral=True)
            return
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = self.player.get_queue_embed(page=self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)


class GuildPlayer:
    """Quản lý phát nhạc và hàng chờ riêng cho từng server."""
    def __init__(self, bot: commands.Bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: List[Song] = []
        self.current: Optional[Song] = None
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.volume: float = 1.0
        self.loop_mode: str = "off"  # "off", "song", "queue"
        
        self.player_message: Optional[discord.Message] = None
        self.player_view: Optional[MusicControlView] = None
        
        self.idle_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    @property
    def is_playing(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_playing())

    @property
    def is_paused(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_paused())

    async def connect(self, channel: discord.VoiceChannel):
        if not self.voice_client or not self.voice_client.is_connected():
            self.voice_client = await channel.connect(reconnect=True, timeout=20.0)
        elif self.voice_client.channel != channel:
            await self.voice_client.move_to(channel)

    async def disconnect(self):
        self.cancel_idle_timer()
        self.queue.clear()
        self.current = None
        if self.voice_client and self.voice_client.is_connected():
            await self.voice_client.disconnect(force=True)
        self.voice_client = None
        await self.disable_player_message()

    def start_idle_timer(self):
        self.cancel_idle_timer()
        self.idle_task = self.bot.loop.create_task(self._idle_disconnect())

    def cancel_idle_timer(self):
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            self.idle_task = None

    async def _idle_disconnect(self):
        try:
            # Chờ 3 phút (180s) nếu không có bài hát nào được phát
            await asyncio.sleep(180)
            if not self.is_playing and not self.is_paused:
                if self.text_channel:
                    try:
                        await self.text_channel.send("💤 Đã tự động rời kênh thoại do không hoạt động trong 3 phút.")
                    except Exception:
                        pass
                await self.disconnect()
        except asyncio.CancelledError:
            pass

    async def set_volume(self, volume: float):
        self.volume = max(0.05, min(1.5, volume))
        if self.voice_client and self.voice_client.source:
            if isinstance(self.voice_client.source, discord.PCMVolumeTransformer):
                self.voice_client.source.volume = self.volume

    def pause(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()

    def resume(self):
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()

    def skip(self):
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            # Khi skip, nếu đang ở chế độ lặp 1 bài, tạm thời bỏ qua bài đó
            if self.loop_mode == "song":
                self.current = None
            self.voice_client.stop()

    def shuffle(self):
        random.shuffle(self.queue)

    async def stop(self):
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"
        if self.voice_client and (self.voice_client.is_playing() or self.voice_client.is_paused()):
            self.voice_client.stop()
        await self.disable_player_message()
        self.start_idle_timer()

    def add_song(self, song: Song):
        self.queue.append(song)
        self.cancel_idle_timer()

    def add_songs(self, songs: List[Song]):
        self.queue.extend(songs)
        self.cancel_idle_timer()

    async def play_next(self):
        async with self._lock:
            if not self.voice_client or not self.voice_client.is_connected():
                return

            # Xử lý lặp bài
            if self.loop_mode == "song" and self.current:
                next_song = self.current
            elif self.loop_mode == "queue" and self.current:
                self.queue.append(self.current)
                next_song = self.queue.pop(0) if self.queue else None
            else:
                next_song = self.queue.pop(0) if self.queue else None

            if not next_song:
                self.current = None
                await self.disable_player_message()
                self.start_idle_timer()
                return

            self.current = next_song
            self.cancel_idle_timer()

            try:
                source = await next_song.get_audio_source(volume=self.volume)
            except Exception as e:
                print(f"[Audio Error] Lỗi tải nguồn phát: {e}", flush=True)
                if self.text_channel:
                    await self.text_channel.send(f"⚠️ Không thể phát **{next_song.title}**: `{e}`. Đang chuyển bài tiếp theo...")
                self.bot.loop.create_task(self.play_next())
                return

            def after_play(error):
                if error:
                    print(f"[Player Error] {error}", flush=True)
                # Chạy play_next trong event loop
                fut = asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
                try:
                    fut.result()
                except Exception:
                    pass

            self.voice_client.play(source, after=after_play)
            await self.send_now_playing_message()

    async def send_now_playing_message(self):
        if not self.text_channel or not self.current:
            return

        embed = self.get_now_playing_embed()
        self.player_view = MusicControlView(self)

        try:
            # Xóa hoặc vô hiệu hóa thông điệp điều khiển cũ nếu có
            if self.player_message:
                try:
                    await self.player_message.delete()
                except Exception:
                    pass

            self.player_message = await self.text_channel.send(embed=embed, view=self.player_view)
        except Exception as e:
            print(f"[Error send NP message] {e}", flush=True)

    async def update_player_message(self):
        if self.player_message and self.current and self.player_view:
            try:
                self.player_view.sync_buttons()
                embed = self.get_now_playing_embed()
                await self.player_message.edit(embed=embed, view=self.player_view)
            except Exception:
                pass

    async def disable_player_message(self):
        if self.player_message:
            try:
                for item in self.player_view.children:
                    item.disabled = True
                await self.player_message.edit(view=self.player_view)
            except Exception:
                pass
            self.player_message = None

    def get_now_playing_embed(self) -> discord.Embed:
        song = self.current
        if not song:
            return discord.Embed(title="🎵 Không có bài hát nào đang phát", color=discord.Color.dark_grey())

        embed = discord.Embed(
            title=f"{song.platform_emoji} Đang Phát: {song.title}",
            url=song.webpage_url,
            color=song.platform_color,
            description=f"🎤 **Nghệ sĩ / Kênh:** `{song.uploader}`\n⏱️ **Thời lượng:** `{song.formatted_duration}`"
        )

        # Hiển thị nền tảng và người yêu cầu
        embed.add_field(name="🌐 Nền tảng", value=f"**{song.platform}**", inline=True)
        embed.add_field(name="🔊 Âm lượng", value=f"`{int(self.volume * 100)}%`", inline=True)
        
        loop_str = "Tắt"
        if self.loop_mode == "song":
            loop_str = "🔂 1 Bài"
        elif self.loop_mode == "queue":
            loop_str = "🔁 Toàn bộ"
        embed.add_field(name="🔁 Lặp lại", value=f"`{loop_str}`", inline=True)

        if self.queue:
            next_song = self.queue[0]
            embed.add_field(
                name="⏭️ Bài tiếp theo",
                value=f"[{next_song.title}]({next_song.webpage_url}) (`{next_song.formatted_duration}`)",
                inline=False
            )
        else:
            embed.add_field(name="⏭️ Bài tiếp theo", value="*Hết hàng chờ*", inline=False)

        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)

        requester_name = song.requester.display_name if song.requester else "Không rõ"
        avatar_url = song.requester.display_avatar.url if song.requester else None
        embed.set_footer(
            text=f"Yêu cầu bởi {requester_name} • Jockey & SoundCloud Music Engine",
            icon_url=avatar_url
        )
        return embed

    def get_queue_embed(self, page: int = 0, per_page: int = 10) -> discord.Embed:
        embed = discord.Embed(
            title="📜 Danh Sách Hàng Chờ Âm Nhạc",
            color=discord.Color.blurple()
        )

        if self.current:
            embed.description = f"**Đang phát:**\n{self.current.platform_emoji} [{self.current.title}]({self.current.webpage_url}) (`{self.current.formatted_duration}`) • {self.current.requester.mention}\n\n{'─' * 35}\n**Hàng chờ ({len(self.queue)} bài):**\n"
        else:
            embed.description = "Hiện không có bài hát nào đang phát.\n\n"

        if not self.queue:
            embed.description += "*Không có bài hát nào trong hàng chờ.*"
            embed.set_footer(text=f"Tổng số: 0 bài • Jockey Music")
            return embed

        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_songs = self.queue[start_idx:end_idx]

        queue_text = []
        for i, s in enumerate(page_songs, start=start_idx + 1):
            queue_text.append(f"`{i:02d}.` {s.platform_emoji} [{s.title}]({s.webpage_url}) - `{s.formatted_duration}` ({s.requester.mention})")

        embed.description += "\n".join(queue_text)
        
        total_duration = sum(s.duration for s in self.queue if s.duration > 0)
        total_pages = max(1, (len(self.queue) + per_page - 1) // per_page)
        embed.set_footer(
            text=f"Trang {page + 1}/{total_pages} • Tổng: {len(self.queue)} bài ({format_duration(total_duration)}) • Lặp: {self.loop_mode.upper()}"
        )
        return embed


class MusicCog(commands.Cog, name="Music"):
    """Hệ thống nghe nhạc đa nền tảng cao cấp hỗ trợ YouTube & SoundCloud."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: Dict[int, GuildPlayer] = {}

    def get_player(self, guild: discord.Guild) -> GuildPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = GuildPlayer(self.bot, guild)
        return self.players[guild.id]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Tự động ngắt kết nối nếu bot ở một mình trong kênh voice."""
        if member.id == self.bot.user.id and after.channel is None:
            # Bot bị kick hoặc bị ngắt kết nối
            if member.guild.id in self.players:
                player = self.players[member.guild.id]
                await player.stop()
                player.voice_client = None
            return

        # Kiểm tra kênh của bot
        if member.guild.id in self.players:
            player = self.players[member.guild.id]
            if player.voice_client and player.voice_client.channel:
                channel = player.voice_client.channel
                # Đếm số người không phải bot
                human_members = [m for m in channel.members if not m.bot]
                if len(human_members) == 0:
                    # Chờ 60s xem có ai vào không rồi rời
                    await asyncio.sleep(60)
                    if player.voice_client and player.voice_client.channel:
                        check_humans = [m for m in player.voice_client.channel.members if not m.bot]
                        if len(check_humans) == 0:
                            if player.text_channel:
                                try:
                                    await player.text_channel.send("👋 Kênh thoại không còn ai nghe, bot xin phép rời kênh nhé!")
                                except Exception:
                                    pass
                            await player.disconnect()

    # ─────────────────────────────────────────────────────────────
    # CORE PLAY LOGIC
    # ─────────────────────────────────────────────────────────────
    async def _handle_play(
        self,
        interaction_or_ctx,
        query: str,
        platform_pref: Optional[str] = None
    ):
        is_slash = isinstance(interaction_or_ctx, discord.Interaction)
        user = interaction_or_ctx.user if is_slash else interaction_or_ctx.author
        guild = interaction_or_ctx.guild
        channel = interaction_or_ctx.channel

        if not user.voice or not user.voice.channel:
            msg = "❌ Bạn cần tham gia một kênh đàm thoại (Voice Channel) trước!"
            if is_slash:
                await interaction_or_ctx.response.send_message(msg, ephemeral=True)
            else:
                await interaction_or_ctx.reply(msg)
            return

        # Defer interaction vì tìm kiếm yt-dlp có thể mất 1-3 giây
        if is_slash:
            await interaction_or_ctx.response.defer()
        else:
            loading_msg = await interaction_or_ctx.send("🔍 Đang tìm kiếm và xử lý âm thanh...")

        player = self.get_player(guild)
        player.text_channel = channel

        # Kết nối vào voice
        try:
            await player.connect(user.voice.channel)
        except Exception as e:
            err_msg = f"❌ Không thể kết nối vào kênh thoại: `{e}`"
            if is_slash:
                await interaction_or_ctx.followup.send(err_msg)
            else:
                await loading_msg.edit(content=err_msg)
            return

        # Lấy bài hát từ extractor
        try:
            songs = await SongExtractor.get_songs(query, platform_preference=platform_pref, requester=user)
        except Exception as e:
            err_msg = f"❌ Lỗi khi tìm kiếm bài hát: `{e}`"
            if is_slash:
                await interaction_or_ctx.followup.send(err_msg)
            else:
                await loading_msg.edit(content=err_msg)
            return

        if not songs:
            not_found = f"❌ Không tìm thấy bài hát nào cho từ khóa: **{query}**"
            if is_slash:
                await interaction_or_ctx.followup.send(not_found)
            else:
                await loading_msg.edit(content=not_found)
            return

        # Thêm bài hát vào hàng chờ
        if len(songs) == 1:
            song = songs[0]
            player.add_song(song)

            embed = discord.Embed(
                title=f"✅ Đã Thêm Vào Hàng Chờ (#{len(player.queue)})",
                description=f"{song.platform_emoji} **[{song.title}]({song.webpage_url})**\n⏱️ Thời lượng: `{song.formatted_duration}` | 👤 Yêu cầu: {user.mention}",
                color=song.platform_color
            )
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)
            embed.set_footer(text=f"Nền tảng: {song.platform} • Jockey Style")

            if is_slash:
                await interaction_or_ctx.followup.send(embed=embed)
            else:
                await loading_msg.edit(content=None, embed=embed)
        else:
            player.add_songs(songs)
            first_platform = songs[0].platform
            color = songs[0].platform_color
            embed = discord.Embed(
                title=f"✅ Đã Thêm Danh Sách Phát ({len(songs)} bài)",
                description=f"🌐 Nền tảng: **{first_platform}**\n👤 Yêu cầu bởi: {user.mention}\nTổng số bài trong hàng chờ: **{len(player.queue)} bài**",
                color=color
            )
            if is_slash:
                await interaction_or_ctx.followup.send(embed=embed)
            else:
                await loading_msg.edit(content=None, embed=embed)

        # Nếu chưa phát bài nào thì bắt đầu phát
        if not player.is_playing and not player.is_paused:
            await player.play_next()

    # ─────────────────────────────────────────────────────────────
    # SLASH COMMANDS
    # ─────────────────────────────────────────────────────────────
    @app_commands.command(
        name="play",
        description="Phát nhạc từ YouTube, SoundCloud, Spotify (hỗ trợ link, playlist hoặc tìm kiếm)"
    )
    @app_commands.describe(
        query="Tên bài hát, link YouTube, SoundCloud hoặc Spotify",
        platform="Chọn nền tảng tìm kiếm nếu không dán link (Mặc định: YouTube)"
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="🔴 YouTube", value="YouTube"),
        app_commands.Choice(name="🟠 SoundCloud", value="SoundCloud"),
        app_commands.Choice(name="🟢 Spotify", value="Spotify"),
    ])
    async def slash_play(
        self,
        interaction: discord.Interaction,
        query: str,
        platform: Optional[app_commands.Choice[str]] = None
    ):
        pref = platform.value if platform else None
        await self._handle_play(interaction, query, pref)

    @app_commands.command(
        name="play_spotify",
        description="Tìm kiếm hoặc phát nhạc trực tiếp từ link Spotify (Bài hát, Album hoặc Playlist)"
    )
    @app_commands.describe(query="Tên bài hát hoặc link Spotify")
    async def slash_play_spotify(self, interaction: discord.Interaction, query: str):
        await self._handle_play(interaction, query, "Spotify")

    @app_commands.command(
        name="play_soundcloud",
        description="Tìm kiếm và phát nhạc trực tiếp từ SoundCloud"
    )
    @app_commands.describe(query="Tên bài hát hoặc link SoundCloud")
    async def slash_play_soundcloud(self, interaction: discord.Interaction, query: str):
        await self._handle_play(interaction, query, "SoundCloud")

    @app_commands.command(
        name="play_youtube",
        description="Tìm kiếm và phát nhạc trực tiếp từ YouTube"
    )
    @app_commands.describe(query="Tên bài hát hoặc link YouTube")
    async def slash_play_youtube(self, interaction: discord.Interaction, query: str):
        await self._handle_play(interaction, query, "YouTube")

    @app_commands.command(name="pause", description="Tạm dừng phát nhạc")
    async def slash_pause(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_playing:
            await interaction.response.send_message("❌ Hiện không có bài hát nào đang phát!", ephemeral=True)
            return
        player.pause()
        await interaction.response.send_message("⏸️ Đã tạm dừng nhạc!")
        await player.update_player_message()

    @app_commands.command(name="resume", description="Tiếp tục phát nhạc")
    async def slash_resume(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.is_paused:
            await interaction.response.send_message("❌ Nhạc không ở trạng thái tạm dừng!", ephemeral=True)
            return
        player.resume()
        await interaction.response.send_message("▶️ Đã tiếp tục phát nhạc!")
        await player.update_player_message()

    @app_commands.command(name="skip", description="Bỏ qua bài hát hiện tại")
    async def slash_skip(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("❌ Không có bài hát nào đang phát!", ephemeral=True)
            return
        title = player.current.title
        player.skip()
        await interaction.response.send_message(f"⏭️ Đã bỏ qua: **{title}**")

    @app_commands.command(name="stop", description="Dừng phát nhạc và xóa toàn bộ hàng chờ")
    async def slash_stop(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        await player.stop()
        await interaction.response.send_message("⏹️ Đã dừng phát nhạc và làm sạch hàng chờ!")

    @app_commands.command(name="queue", description="Xem danh sách các bài hát trong hàng chờ")
    async def slash_queue(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        view = QueuePaginationView(player, author=interaction.user)
        embed = player.get_queue_embed(page=0)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="nowplaying", description="Xem thông tin và bảng điều khiển bài hát đang phát")
    async def slash_nowplaying(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("🎵 Hiện không có bài hát nào đang phát!", ephemeral=True)
            return
        embed = player.get_now_playing_embed()
        view = MusicControlView(player)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="volume", description="Điều chỉnh âm lượng phát nhạc (1 - 150%)")
    @app_commands.describe(percent="Mức âm lượng từ 1 đến 150")
    async def slash_volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 1, 150]):
        player = self.get_player(interaction.guild)
        await player.set_volume(percent / 100.0)
        await interaction.response.send_message(f"🔊 Đã điều chỉnh âm lượng sang: **{percent}%**")
        await player.update_player_message()

    @app_commands.command(name="loop", description="Thay đổi chế độ lặp lại bài hát")
    @app_commands.describe(mode="Chọn chế độ lặp")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Tắt lặp (Off)", value="off"),
        app_commands.Choice(name="🔂 Lặp 1 bài hiện tại", value="song"),
        app_commands.Choice(name="🔁 Lặp toàn bộ hàng chờ", value="queue"),
    ])
    async def slash_loop(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        player = self.get_player(interaction.guild)
        player.loop_mode = mode.value
        mode_names = {"off": "Tắt", "song": "Lặp bài hiện tại", "queue": "Lặp toàn bộ hàng chờ"}
        await interaction.response.send_message(f"🔁 Đã chuyển chế độ lặp sang: **{mode_names[mode.value]}**")
        await player.update_player_message()

    @app_commands.command(name="shuffle", description="Trộn ngẫu nhiên danh sách phát trong hàng chờ")
    async def slash_shuffle(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        if len(player.queue) < 2:
            await interaction.response.send_message("❌ Cần ít nhất 2 bài trong hàng chờ để trộn!", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(f"🔀 Đã xáo trộn thứ tự **{len(player.queue)}** bài hát trong hàng chờ!")
        await player.update_player_message()

    @app_commands.command(name="remove", description="Xóa một bài hát khỏi hàng chờ theo vị trí số")
    @app_commands.describe(index="Vị trí của bài hát trong lệnh /queue (Bắt đầu từ 1)")
    async def slash_remove(self, interaction: discord.Interaction, index: int):
        player = self.get_player(interaction.guild)
        if not (1 <= index <= len(player.queue)):
            await interaction.response.send_message(f"❌ Vị trí không hợp lệ! Hàng chờ hiện có {len(player.queue)} bài.", ephemeral=True)
            return
        removed = player.queue.pop(index - 1)
        await interaction.response.send_message(f"🗑️ Đã xóa bài #{index}: **{removed.title}** khỏi hàng chờ!")

    @app_commands.command(name="disconnect", description="Cho bot rời khỏi kênh đàm thoại")
    async def slash_disconnect(self, interaction: discord.Interaction):
        player = self.get_player(interaction.guild)
        await player.disconnect()
        await interaction.response.send_message("👋 Bot đã ngắt kết nối và rời khỏi kênh thoại!")

    # ─────────────────────────────────────────────────────────────
    # PREFIX COMMANDS (!play, !skip, !queue, etc.)
    # ─────────────────────────────────────────────────────────────
    @commands.command(name="play", aliases=["p"])
    async def prefix_play(self, ctx: commands.Context, *, query: str):
        """Lệnh prefix !play <tên hoặc link>"""
        await self._handle_play(ctx, query, None)

    @commands.command(name="playsc", aliases=["psc"])
    async def prefix_playsc(self, ctx: commands.Context, *, query: str):
        """Lệnh prefix !playsc <tên hoặc link SoundCloud>"""
        await self._handle_play(ctx, query, "SoundCloud")

    @commands.command(name="playspotify", aliases=["playsp", "psp"])
    async def prefix_playspotify(self, ctx: commands.Context, *, query: str):
        """Lệnh prefix !playspotify <tên hoặc link Spotify>"""
        await self._handle_play(ctx, query, "Spotify")

    @commands.command(name="playyt", aliases=["pyt"])
    async def prefix_playyt(self, ctx: commands.Context, *, query: str):
        """Lệnh prefix !playyt <tên hoặc link YouTube>"""
        await self._handle_play(ctx, query, "YouTube")

    @commands.command(name="skip", aliases=["s", "next"])
    async def prefix_skip(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if not player.current:
            await ctx.send("❌ Không có bài hát nào đang phát!")
            return
        title = player.current.title
        player.skip()
        await ctx.send(f"⏭️ Đã bỏ qua: **{title}**")

    @commands.command(name="pause")
    async def prefix_pause(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if not player.is_playing:
            await ctx.send("❌ Hiện không có bài hát nào đang phát!")
            return
        player.pause()
        await ctx.send("⏸️ Đã tạm dừng nhạc!")
        await player.update_player_message()

    @commands.command(name="resume")
    async def prefix_resume(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if not player.is_paused:
            await ctx.send("❌ Nhạc không ở trạng thái tạm dừng!")
            return
        player.resume()
        await ctx.send("▶️ Đã tiếp tục phát nhạc!")
        await player.update_player_message()

    @commands.command(name="stop")
    async def prefix_stop(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        await player.stop()
        await ctx.send("⏹️ Đã dừng phát nhạc và làm sạch hàng chờ!")

    @commands.command(name="queue", aliases=["q"])
    async def prefix_queue(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        view = QueuePaginationView(player, author=ctx.author)
        embed = player.get_queue_embed(page=0)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="np", aliases=["nowplaying"])
    async def prefix_np(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if not player.current:
            await ctx.send("🎵 Hiện không có bài hát nào đang phát!")
            return
        embed = player.get_now_playing_embed()
        view = MusicControlView(player)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="volume", aliases=["vol"])
    async def prefix_volume(self, ctx: commands.Context, val: int):
        if not (1 <= val <= 150):
            await ctx.send("❌ Âm lượng phải nằm trong khoảng từ 1 đến 150!")
            return
        player = self.get_player(ctx.guild)
        await player.set_volume(val / 100.0)
        await ctx.send(f"🔊 Đã đổi âm lượng sang **{val}%**!")
        await player.update_player_message()

    @commands.command(name="loop")
    async def prefix_loop(self, ctx: commands.Context, mode: Optional[str] = None):
        player = self.get_player(ctx.guild)
        if not mode:
            modes = ["off", "song", "queue"]
            mode = modes[(modes.index(player.loop_mode) + 1) % len(modes)]
        mode = mode.lower()
        if mode not in ["off", "song", "queue"]:
            await ctx.send("❌ Chế độ không hợp lệ! Dùng: `off`, `song` hoặc `queue`")
            return
        player.loop_mode = mode
        mode_names = {"off": "Tắt", "song": "Lặp bài hiện tại 🔂", "queue": "Lặp toàn bộ hàng chờ 🔁"}
        await ctx.send(f"🔁 Chế độ lặp: **{mode_names[mode]}**")
        await player.update_player_message()

    @commands.command(name="shuffle")
    async def prefix_shuffle(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        if len(player.queue) < 2:
            await ctx.send("❌ Cần ít nhất 2 bài trong hàng chờ để trộn!")
            return
        player.shuffle()
        await ctx.send(f"🔀 Đã xáo trộn danh sách phát ({len(player.queue)} bài)!")
        await player.update_player_message()

    @commands.command(name="leave", aliases=["dc", "disconnect"])
    async def prefix_leave(self, ctx: commands.Context):
        player = self.get_player(ctx.guild)
        await player.disconnect()
        await ctx.send("👋 Bot đã rời khỏi kênh thoại!")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
