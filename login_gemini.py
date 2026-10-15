"""
Script hỗ trợ đăng nhập tài khoản Google ban đầu trên Chrome for Testing (CfT).
- Mở trình duyệt ở chế độ giao diện trực quan (headless=False).
- Lưu vĩnh viễn cookies và session vào thư mục profile riêng.
- Bật cờ bypass Google Security để không bị báo 'Trình duyệt không an toàn'.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Đảm bảo hiển thị tiếng Việt trên terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CFT_PATH = os.getenv("CFT_EXECUTABLE_PATH", r"C:\ChromeForTesting\chrome-win64\chrome.exe")
PROFILE_DIR = os.getenv("CFT_PROFILE_DIR", os.path.join(ROOT_DIR, "gemini_profile"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

async def run_login():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ Lỗi: Chưa cài đặt playwright! Chạy lệnh: pip install playwright")
        return

    os.makedirs(PROFILE_DIR, exist_ok=True)
    print("=" * 60)
    print("🚀 ĐANG KHỞI CHẠY MICROSOFT EDGE ĐỂ ĐĂNG NHẬP GOOGLE")
    print(f"📂 Thư mục Session lưu trữ: {PROFILE_DIR}")
    print("=" * 60)

    async with async_playwright() as p:
        launch_kwargs = {
            "user_data_dir": PROFILE_DIR,
            "headless": False,  # Chế độ có giao diện để bạn thao tác bằng tay
            "channel": "msedge",  # Microsoft Edge bản địa
            "user_agent": USER_AGENT,
            "viewport": {"width": 1280, "height": 850},
            "args": [
                # CỜ QUAN TRỌNG NHẤT: Bỏ kiểm duyệt bot của Google để cho phép đăng nhập
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
            ],
            "ignore_default_args": ["--enable-automation"],
        }
        if CFT_PATH and os.path.exists(CFT_PATH):
            launch_kwargs["executable_path"] = CFT_PATH

        context = await p.chromium.launch_persistent_context(**launch_kwargs)

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        print("\n👉 Đang chuyển hướng đến trang đăng nhập Google / Gemini...")
        await page.goto("https://accounts.google.com/", wait_until="domcontentloaded")

        print("\n" + "★" * 60)
        print("👉 BẠN HÃY THAO TÁC TRỰC TIẾP TRÊN CỬA SỔ TRÌNH DUYỆT:")
        print("1. Điền Email và Mật khẩu Google của bạn.")
        print("2. Vượt qua mã xác thực 2FA / CAPTCHA (nếu có).")
        print("3. Sau khi đăng nhập xong tài khoản Google, hãy vào: https://gemini.google.com/app")
        print("★" * 60)
        print("\n⏳ Script đang chờ bạn đăng nhập xong...")
        print("💡 Khi bạn đã vào được giao diện chat chính của Gemini, hãy bấm phím [ENTER] tại terminal này để hoàn tất!\n")

        # Cho phép chờ người dùng gõ Enter hoặc tự động phát hiện URL gemini
        loop = asyncio.get_event_loop()
        wait_enter_task = loop.run_in_executor(None, input, "👉 Bấm ENTER tại đây sau khi bạn đã đăng nhập xong: ")

        async def check_url_task():
            while True:
                await asyncio.sleep(2)
                if "gemini.google.com/app" in page.url:
                    print("\n🎉 Đã phát hiện bạn truy cập thành công vào gemini.google.com/app!")
                    break

        done, pending = await asyncio.wait(
            [asyncio.create_task(check_url_task()), wait_enter_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        for task in pending:
            task.cancel()

        print("\n💾 Đang lưu cookie và phiên đăng nhập...")
        await asyncio.sleep(2)
        await context.close()
        print("✅ ĐÃ LƯU PHIÊN ĐĂNG NHẬP THÀNH CÔNG VÀO THƯ MỤC 'gemini_profile'!")
        print("👉 Từ bây giờ bot của bạn có thể chạy chế độ nền (headless) mà không cần đăng nhập lại nữa.\n")
        os._exit(0)

if __name__ == "__main__":
    asyncio.run(run_login())
