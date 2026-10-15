# 🤖 Discord All-in-One Bot

Bot Discord đa chức năng được phát triển bằng Python (`discord.py 2.x`), hỗ trợ đầy đủ các tính năng giải trí, hệ thống rạp chiếu phim, AI chatbot và nghe nhạc đa nền tảng chuẩn Jockey Music.

---

## 🌟 Tính Năng Nổi Bật

### 🎵 1. Hệ Thống Âm Nhạc Đa Nền Tảng (Jockey & SoundCloud Engine)
- **Hỗ trợ 3 nền tảng lớn:** YouTube, SoundCloud và Spotify (kể cả link rút gọn `on.soundcloud.com`, album, playlist).
- **Spotify Bridge:** Nhận diện link Spotify, trích xuất metadata và tự động stream audio chất lượng cao.
- **Bảng điều khiển tương tác (Interactive Controller):**
  - Tạm dừng / Tiếp tục (`⏯️`)
  - Bỏ qua bài (`⏭️`)
  - Chế độ lặp (`🔁` - Tắt / 1 bài / Toàn bộ queue)
  - Trộn bài ngẫu nhiên (`🔀`)
  - Hàng chờ phân trang (`📜`)
  - Chỉnh âm lượng modal popup (`🔉` / `🔊` / `🎚️` từ 1% đến 150%)
- **Tự động ngắt kết nối thông minh:** Tự rời kênh thoại sau 3 phút không có bài hát hoặc khi mọi người rời phòng.

### ⏰ 2. Hẹn Giờ Nhắc Nhở (`/remind`)
- Nhập thời gian theo định dạng chuẩn `hours:minutes:seconds` (Ví dụ: `0:15:00`, `1:30:00`, `0:0:30`).
- Tự động tag tên người dùng và gửi thông báo vào đúng kênh hoặc DM khi đến hạn.
- Lưu trữ SQLite vĩnh viễn (không mất lời nhắc khi bot khởi động lại).

### 🎬 3. Hệ Thống Rạp Phim Server (Movie Rating & Showcase)
- Thêm phim, dán poster, chấm điểm 1.0 - 5.0 sao.
- Bảng xếp hạng phim hay nhất và nhà phê bình tích cực nhất server.
- Kênh showcase tự động cập nhật điểm số theo thời gian thực với giao diện 2 trang.

### 🤖 4. Trí Tuệ Nhân Tạo (GPT & Gemini Browser)
- Tích hợp GPT AI tra cứu Internet thời gian thực.
- Tự động hóa trình duyệt Microsoft Edge tương tác trực tiếp với Gemini Web.
- Context menu chuột phải vào tin nhắn bất kỳ để hỏi AI.

### 🎲 5. Mini-game & Tương Tác
- Quay số may mắn `/gru` với animation hiệu ứng slot machine.
- Văn mẫu chửi bậy `/chuibay` và phản hồi siêu cute `/rep`.

---

## 🚀 Hướng Dẫn Cài Đặt

### 1. Yêu cầu hệ thống
- Python 3.10+
- [FFmpeg](https://ffmpeg.org/) (đã thêm vào PATH hệ thống)

### 2. Cài đặt thư viện
```bash
git clone https://github.com/N4NH/DiscordBot.git
cd DiscordBot
pip install -r requirements.txt
```

### 3. Cấu hình biến môi trường
Tạo file `.env` từ file mẫu `.env.example`:
```bash
cp .env.example .env
```
Điền token bot Discord của bạn vào:
```env
DISCORD_TOKEN=your_token_here
```

### 4. Khởi chạy Bot
```bash
python main.py
```

---

## 📜 Giấy Phép
Dự án được phân phối dưới giấy phép MIT License.
