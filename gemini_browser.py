import asyncio
import os
import re
import sys
from typing import Optional
from dotenv import load_dotenv

# Đảm bảo hiển thị unicode trên terminal Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BROWSER_PATH = os.getenv("CFT_EXECUTABLE_PATH", "").strip() or None
DEFAULT_BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge").strip()
DEFAULT_PROFILE_DIR = os.getenv(
    "CFT_PROFILE_DIR",
    os.path.join(ROOT_DIR, "gemini_profile")
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

GEMINI_URL = "https://gemini.google.com/app"


class GeminiBrowserClient:
    """
    Client quản lý trình duyệt Microsoft Edge / Chromium tự động hóa tối ưu tốc độ cao để tương tác với Gemini Web.
    - Mặc định dùng Microsoft Edge (channel='msedge') bản địa trên Windows siêu mượt, không giật lag.
    - Hỗ trợ lưu trữ vĩnh viễn Google Account session qua persistent context.
    - Bật đầy đủ cờ chống phát hiện tự động hóa (bypass AutomationControlled).
    - Tích hợp asyncio.Lock() đảm bảo tuần tự hóa các câu hỏi, tránh xung đột input box.
    """

    def __init__(
        self,
        executable_path: Optional[str] = DEFAULT_BROWSER_PATH,
        channel: Optional[str] = DEFAULT_BROWSER_CHANNEL,
        user_data_dir: str = DEFAULT_PROFILE_DIR,
        headless: bool = False
    ):
        self.executable_path = executable_path
        self.channel = channel
        self.user_data_dir = user_data_dir
        self.headless = headless
        self._lock = asyncio.Lock()

        self._playwright = None
        self._context = None
        self._page = None
        self._is_ready = False

    @property
    def is_busy(self) -> bool:
        """Kiểm tra xem trình duyệt có đang bận xử lý câu hỏi không."""
        return self._lock.locked()

    async def start(self):
        """Khởi động trình duyệt Microsoft Edge / Chromium và chuẩn bị sẵn trang Gemini."""
        if self._is_ready:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Chưa cài đặt thư viện Playwright! Vui lòng chạy lệnh: pip install playwright"
            )

        os.makedirs(self.user_data_dir, exist_ok=True)

        self._playwright = await async_playwright().start()

        launch_args = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "viewport": {"width": 1280, "height": 850},
            "user_agent": USER_AGENT,
            "locale": "vi-VN",
            "timezone_id": "Asia/Ho_Chi_Minh",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-features=CalculateNativeWinOcclusion",
                "--disable-ipc-flooding-protection",
                "--disable-hang-monitor",
                "--disable-sync",
                "--disable-domain-reliability",
                "--disable-component-update",
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
                "--enable-gpu-rasterization",
                "--enable-zero-copy",
            ],
            "ignore_default_args": ["--enable-automation"],
        }

        # Ưu tiên khởi chạy Microsoft Edge hoặc đường dẫn tùy chỉnh
        if self.executable_path and os.path.exists(self.executable_path):
            launch_args["executable_path"] = self.executable_path
            print(f"[GeminiClient] Khởi chạy trình duyệt tùy chỉnh: {self.executable_path}", flush=True)
        elif self.channel and self.channel.lower() in ["msedge", "edge"]:
            launch_args["channel"] = "msedge"
            print("[GeminiClient] Khởi chạy Microsoft Edge bản địa Windows tốc độ cao...", flush=True)
        else:
            print("[GeminiClient] Khởi chạy Chromium chính thức hiệu năng cao...", flush=True)

        # Khởi chạy Persistent Context với các cờ bypass phát hiện bot và tối ưu tối đa hiệu năng
        self._context = await self._playwright.chromium.launch_persistent_context(**launch_args)

        # Ẩn cờ navigator.webdriver
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.navigator.chrome = {
                runtime: {}
            };
        """)

        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()

        print("[GeminiClient] Dang truy cap gemini.google.com...", flush=True)
        await self._page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)

        # Tự động đóng banner giới thiệu / popup nếu có
        await self._dismiss_popups()

        self._is_ready = True
        print("[GeminiClient] Trinh duyet da san sang nhan lenh!", flush=True)

    async def _dismiss_popups(self):
        """Tự động đóng các nút thông báo chào mừng / popup ban đầu."""
        if not self._page:
            return
        popup_btn_texts = ["Bắt đầu thôi", "Tiếp tục", "Đồng ý", "Tôi đã hiểu", "Dismiss", "Got it"]
        for txt in popup_btn_texts:
            try:
                btn = self._page.locator(f"button:has-text('{txt}')").first
                if await btn.is_visible(timeout=400):
                    await btn.click()
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    async def stop(self):
        """Dọn dẹp và đóng trình duyệt an toàn."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._is_ready = False
        print("[GeminiClient] Da dong trinh duyet Gemini.", flush=True)

    async def _find_input_element(self):
        """Tìm vùng soạn thảo của Gemini (Quill editor bên trong rich-textarea)."""
        input_selectors = [
            "rich-textarea div[contenteditable='true']",
            "div[contenteditable='true'][role='textbox']",
            "div.ql-editor[contenteditable='true']",
            "div[contenteditable='true']",
            "textarea"
        ]
        for sel in input_selectors:
            try:
                locator = self._page.locator(sel).first
                if await locator.is_visible(timeout=1500):
                    return locator
            except Exception:
                continue
        return None

    async def _check_gemini_error(self) -> Optional[str]:
        """Phát hiện nếu Gemini hiển thị lỗi hoặc thông báo sự cố trên màn hình."""
        try:
            error_selectors = [
                ".error-message",
                "[data-test-id='error-message']",
                ".error-container",
                "div.alert-error",
                "span:has-text('Đã xảy ra lỗi')",
                "span:has-text('Something went wrong')",
                "div:has-text('Có sự cố xảy ra')"
            ]
            for sel in error_selectors:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=100):
                    txt = await el.inner_text()
                    if txt and txt.strip():
                        return txt.strip()
        except Exception:
            pass
        return None

    async def _wait_for_generation_complete(self, initial_count: int, timeout_sec: int = 600) -> str:
        """
        Cơ chế phát hiện Gemini hoàn tất sinh câu trả lời:
        - TỐI ƯU TỐC ĐỘ CAO: KHÔNG cào DOM hay gọi evaluate() khi đang streaming chữ để Chromium không bị lag.
        - Timeout mặc định: 600 giây (10 phút).
        - Theo dõi trạng thái nút Dừng (Stop) biến mất, sau đó lấy văn bản sạch hoàn tất.
        """
        start_time = asyncio.get_event_loop().time()
        last_heartbeat = start_time
        last_text = ""
        stable_count = 0

        timeout_label = f"{timeout_sec // 60} phút" if timeout_sec and timeout_sec >= 60 else f"{timeout_sec}s"
        print(f"[GeminiClient] Đang theo dõi tiến trình phản hồi của Gemini (timeout: {timeout_label})...", flush=True)

        while True:
            now = asyncio.get_event_loop().time()
            elapsed = now - start_time

            # Nếu quá thời gian chờ (mặc định 10 phút = 600s)
            if timeout_sec is not None and timeout_sec > 0 and elapsed > timeout_sec:
                if last_text:
                    print(f"[GeminiClient] Hết thời gian chờ {timeout_label}, trả về nội dung đã nhận được.", flush=True)
                    return last_text
                raise TimeoutError(f"Quá thời gian chờ phản hồi từ Gemini ({timeout_label})!")

            # Log nhịp tim mỗi 25 giây
            if now - last_heartbeat >= 25:
                print(f"[GeminiClient] Vẫn đang đợi Gemini sinh câu trả lời... (đã chờ {elapsed:.0f}s)", flush=True)
                last_heartbeat = now

            # 1. Kiểm tra xem Gemini có văng thông báo lỗi server trên màn hình không
            err_msg = await self._check_gemini_error()
            if err_msg:
                print(f"[GeminiClient] Phát hiện thông báo lỗi từ Gemini: {err_msg}", flush=True)
                return f"⚠️ **Thông báo từ Gemini:** {err_msg}"

            # 2. Kiểm tra xem nút Stop có đang hiển thị không (Gemini đang stream văn bản)
            stop_btn = self._page.locator(
                "button[aria-label*='Dừng'], button[aria-label*='Stop'], button:has(mat-icon:has-text('stop'))"
            )
            is_generating = False
            try:
                is_generating = (await stop_btn.count() > 0) and (await stop_btn.first.is_visible())
            except Exception:
                pass

            # QUAN TRỌNG NHẤT ĐỂ CHỐNG LAG:
            # Nếu Gemini đang sinh chữ, CHỈ NGHỈ NGƠI, KHÔNG chạm vào DOM hay gọi script evaluate
            if is_generating:
                stable_count = 0
                await asyncio.sleep(0.5)
                continue

            # 3. Khi nút Stop đã biến mất: Trích xuất nội dung văn bản sạch
            current_text = await self._extract_clean_response_text()

            # 4. Kiểm tra xem khối response đã có footer complete chưa
            footer = self._page.locator("div.response-footer.complete")
            is_footer_complete = False
            try:
                is_footer_complete = await footer.count() > 0
            except Exception:
                pass

            if current_text:
                if is_footer_complete:
                    return current_text

                if current_text == last_text:
                    stable_count += 1
                    # Sau khi Stop tắt, chỉ cần 2 nhịp ổn định (~0.6s) là chốt kết quả ngay lập tức
                    if stable_count >= 2:
                        return current_text
                else:
                    stable_count = 0

            last_text = current_text
            await asyncio.sleep(0.3)

    async def _extract_clean_response_text(self) -> str:
        """
        Trích xuất văn bản câu trả lời sạch từ Gemini, loại bỏ hoàn toàn các chip dẫn chứng nguồn
        (ví dụ: 'JH Figure', 'JH Figure + 1', 'Wikipedia + 2', các pill nút nguồn).
        """
        try:
            clean_text = await self._page.evaluate("""() => {
                const messages = document.querySelectorAll('message-content');
                if (messages.length === 0) return '';
                const lastMsg = messages[messages.length - 1];
                const clone = lastMsg.cloneNode(true);

                // Loại bỏ tất cả các thành phần dẫn chứng nguồn và nút tương tác
                const junkSelectors = [
                    'sources-list',
                    'source-chip',
                    'source-pill',
                    'citation-chip',
                    'gem-source-chip',
                    'grounding-chip',
                    'grounding-button',
                    'grounding-drawer',
                    'mat-chip',
                    'mat-chip-row',
                    'gem-chip',
                    '.source-chip',
                    '.citation-chip',
                    '.grounding-chip',
                    '.citation-marker',
                    '.inline-citation',
                    '[data-test-id*="citation"]',
                    '[data-test-id*="source"]',
                    '[data-test-id*="grounding"]',
                    '.fact-check-badge',
                    '.source-attribution',
                    'button[aria-label*="Nguồn"]',
                    'button[aria-label*="Source"]',
                    'button[aria-label*="trích dẫn"]',
                    'button[aria-label*="citation"]',
                    'a[href*="grounding"]',
                    'a.source-pill',
                    '.response-footer',
                    'message-actions'
                ];

                junkSelectors.forEach(sel => {
                    clone.querySelectorAll(sel).forEach(node => node.remove());
                });

                const md = clone.querySelector('div.markdown') || clone;
                return md.innerText ? md.innerText.trim() : '';
            }""")
        except Exception:
            clean_text = ""

        if not clean_text:
            return ""

        # Dọn dẹp các dòng rác dẫn chứng nguồn dạng "Tên Nguồn + 1"
        cleaned_lines = []
        for line in clean_text.splitlines():
            stripped = line.strip()
            # Bỏ các dòng dạng "JH Figure", "JH Figure + 1", "+ 1", "Wikipedia + 2"
            if re.match(r'^(?:[A-Za-z0-9\.\-_\s]+\s*\+\s*\d+|\+\s*\d+|JH Figure.*)$', stripped, re.IGNORECASE):
                continue
            if re.match(r'^(?:Source|Nguồn|Trích dẫn):\s*.*$', stripped, re.IGNORECASE):
                continue
            cleaned_lines.append(line)

        res = "\n".join(cleaned_lines)
        res = re.sub(r'\n{3,}', '\n\n', res)
        return res.strip()

    async def ask(self, prompt: str, image_path: Optional[str] = None, timeout: int = 600) -> str:
        """
        Gửi prompt (kèm ảnh tùy chọn) và trả về kết quả Markdown sạch.
        Hàm được bọc qua asyncio.Lock() để hàng đợi câu hỏi hoạt động tuần tự.
        timeout=600: Chờ tối đa 10 phút (600 giây) theo yêu cầu.
        """
        async with self._lock:
            if not self._is_ready:
                await self.start()

            # Đảm bảo đang ở trang Gemini
            if "gemini.google.com" not in self._page.url:
                await self._page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(1.5)

            await self._dismiss_popups()

            # Đếm số lượng tin nhắn hiện tại để phân biệt tin mới
            initial_count = await self._page.locator("message-content").count()

            # 1. Tìm ô nhập văn bản
            input_box = await self._find_input_element()
            if not input_box:
                await self._page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                await self._dismiss_popups()
                input_box = await self._find_input_element()
                if not input_box:
                    raise RuntimeError(
                        "Không tìm thấy ô nhập câu hỏi trên web Gemini! Bạn đã đăng nhập tài khoản chưa?"
                    )

            # 2. Xử lý tải ảnh lên nếu có
            if image_path and os.path.exists(image_path):
                try:
                    plus_btn = self._page.locator(
                        "button[aria-label*='Nội dung tải lên'], button[aria-label*='Upload']"
                    ).first
                    if await plus_btn.is_visible(timeout=1000):
                        await plus_btn.click()
                        await asyncio.sleep(0.5)

                    file_input = self._page.locator("input[type='file'][accept*='image']").first
                    await file_input.set_input_files(image_path)
                    # Chờ thumbnail ảnh xuất hiện
                    await asyncio.sleep(2.0)
                except Exception as e:
                    print(f"[GeminiClient] Khong the tai anh len: {e}", flush=True)

            # 3. Focus và gõ câu hỏi bằng Playwright keyboard
            await input_box.click()
            await asyncio.sleep(0.2)

            # Xóa sạch nội dung cũ nếu có (Ctrl+A -> Backspace)
            await self._page.keyboard.press("Control+A")
            await self._page.keyboard.press("Backspace")
            await asyncio.sleep(0.1)

            # Gõ văn bản mô phỏng bàn phím thực
            prompt_text = prompt if prompt.strip() else "Hãy phân tích và mô tả hình ảnh này giúp tôi."
            await self._page.keyboard.insert_text(prompt_text)
            await asyncio.sleep(0.3)

            # 3. Gửi tin nhắn bằng cách bấm Enter hoặc nút Send
            sent = False
            send_btn = self._page.locator("button[aria-label*='Gửi'], button[aria-label*='Send']").first
            if await send_btn.is_visible(timeout=500):
                try:
                    await send_btn.click()
                    sent = True
                except Exception:
                    pass

            if not sent:
                await self._page.keyboard.press("Enter")

            # 4. Chờ sinh phản hồi và trích xuất kết quả (không giới hạn timeout)
            response_text = await self._wait_for_generation_complete(
                initial_count=initial_count,
                timeout_sec=timeout
            )

            # Lên lịch tự động xóa phiên chat và mở cuộc trò chuyện mới sau 3 giây để tránh ngáo context
            asyncio.create_task(self.clean_reset_session(delay_sec=3.0))

            return response_text

    async def clean_reset_session(self, delay_sec: float = 3.0):
        """
        Sau khi trả lời xong, chờ delay_sec (mặc định 3s):
        1. Xóa vĩnh viễn cuộc trò chuyện khỏi thanh sidebar/taskbar để không bị rác và không ngáo context.
        2. Bấm Cuộc trò chuyện mới / đưa về trang trắng tinh.
        """
        await asyncio.sleep(delay_sec)
        async with self._lock:
            if not self._is_ready or not self._page:
                return

            print("[GeminiClient] Bắt đầu dọn dẹp và xóa cuộc trò chuyện khỏi thanh task...", flush=True)

            try:
                # 1. Đảm bảo sidebar đang mở để hiển thị danh sách cuộc trò chuyện
                open_sidebar_btn = self._page.locator("button[aria-label*='Mở thanh bên']").first
                if await open_sidebar_btn.is_visible(timeout=500):
                    try:
                        await open_sidebar_btn.click()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass

                # 2. Vòng lặp xóa các cuộc trò chuyện trên thanh task (xóa tối đa 5 cuộc trò chuyện gần nhất để dọn sạch hoàn toàn)
                for delete_iter in range(5):
                    deleted_any = False

                    # Hover qua mục trò chuyện đầu tiên trong danh sách lịch sử
                    chat_items = self._page.locator(
                        ".chat-history-list > *, "
                        ".chat-history gem-nav-list-item, "
                        ".chat-history a, "
                        "bard-sidenav .chat-history-list div, "
                        "side-navigation-content .chat-history-item, "
                        "gem-nav-list-item:has(a[href*='/app/'])"
                    )

                    if await chat_items.count() > 0:
                        try:
                            await chat_items.first.hover(timeout=1000)
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass

                    # Tìm nút 3 chấm (Lựa chọn khác / More options / menu-button)
                    more_btn = self._page.locator(
                        "button[aria-label*='Lựa chọn khác'], "
                        "button[aria-label*='Tùy chọn khác'], "
                        "button[aria-label*='tùy chọn'], "
                        "button[aria-label*='lựa chọn'], "
                        "button[aria-label*='More options'], "
                        "button[aria-label*='options'], "
                        "[data-test-id='conversation-actions-menu-button'], "
                        ".chat-history button:has(mat-icon), "
                        ".chat-history-list button"
                    ).first

                    more_btn_visible = False
                    try:
                        more_btn_visible = await more_btn.is_visible(timeout=800)
                    except Exception:
                        pass

                    if more_btn_visible:
                        try:
                            await more_btn.click(force=True, timeout=1500)
                            await asyncio.sleep(0.4)
                        except Exception:
                            pass
                    else:
                        # Thử kích hoạt nút 3 chấm bằng JavaScript nếu hover chưa kịp hiện
                        clicked_via_js = await self._page.evaluate("""() => {
                            const btns = Array.from(document.querySelectorAll(
                                '.chat-history button, .chat-history-list button, bard-sidenav button[aria-label*="Lựa chọn"], bard-sidenav button[aria-label*="Tùy chọn"], bard-sidenav button[aria-label*="options"]'
                            ));
                            if (btns.length > 0) {
                                btns[0].click();
                                return true;
                            }
                            const firstItem = document.querySelector('.chat-history-list > *');
                            if (firstItem) {
                                const b = firstItem.querySelector('button');
                                if (b) {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        }""")
                        if clicked_via_js:
                            await asyncio.sleep(0.4)

                    # Bấm nút Xóa trong menu thả xuống
                    delete_opt = self._page.locator(
                        "button[role='menuitem']:has-text('Xóa'), "
                        "button[role='menuitem']:has-text('Delete'), "
                        ".mat-mdc-menu-item:has-text('Xóa'), "
                        ".mat-mdc-menu-item:has-text('Delete'), "
                        "button:has-text('Xóa'), "
                        "button:has(mat-icon:has-text('delete'))"
                    ).first

                    delete_opt_visible = False
                    try:
                        delete_opt_visible = await delete_opt.is_visible(timeout=1000)
                    except Exception:
                        pass

                    if delete_opt_visible:
                        await delete_opt.click()
                        await asyncio.sleep(0.5)

                        # Bấm nút xác nhận "Xóa" trong hộp thoại xác nhận (modal dialog)
                        confirm_btn = self._page.locator(
                            "mat-dialog-actions button:has-text('Xóa'), "
                            "mat-dialog-actions button:has-text('Delete'), "
                            "[role='dialog'] button:has-text('Xóa'), "
                            "[role='dialog'] button:has-text('Delete'), "
                            "button.mat-mdc-unelevated-button:has-text('Xóa'), "
                            "button.mat-mdc-unelevated-button:has-text('Delete')"
                        ).last

                        try:
                            if await confirm_btn.is_visible(timeout=1500):
                                await confirm_btn.click()
                                deleted_any = True
                                print(f"[GeminiClient] Đã xóa thành công 1 cuộc trò chuyện (lần {delete_iter + 1})", flush=True)
                                await asyncio.sleep(0.8)
                        except Exception as e:
                            print(f"[GeminiClient] Không thể bấm xác nhận xóa: {e}", flush=True)

                    if not deleted_any:
                        # Đã xóa hết hoặc không còn cuộc trò chuyện nào để xóa
                        break

            except Exception as e:
                print(f"[GeminiClient] Lưu ý khi xóa lịch sử trò chuyện: {e}", flush=True)

            # 3. Đưa giao diện về trang trắng "Cuộc trò chuyện mới" để hoàn toàn sạch context
            try:
                new_chat = self._page.locator(
                    "a[href='/app'], "
                    "[data-test-id='new-chat-button'], "
                    "a:has-text('Cuộc trò chuyện mới'), "
                    "a[aria-label*='Cuộc trò chuyện mới']"
                ).first

                if await new_chat.is_visible(timeout=1000):
                    await new_chat.click()
                    await asyncio.sleep(0.8)
                else:
                    await self._page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                try:
                    await self._page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass

            await self._dismiss_popups()
            print("[GeminiClient] Đã reset phiên chat và xóa sạch thanh task thành công!", flush=True)


def split_discord_message(content: str, max_length: int = 1900) -> list[str]:
    """
    Chia nhỏ tin nhắn an toàn cho giới hạn 2000 ký tự của Discord.
    - Ưu tiên cắt theo đoạn văn hoặc dòng.
    - Bảo toàn codeblock markdown nếu bị cắt ngang.
    """
    if len(content) <= max_length:
        return [content]

    chunks = []
    lines = content.splitlines(keepends=True)
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for line in lines:
        code_match = re.match(r"^```(\w*)", line.strip())
        if code_match:
            if not in_code_block:
                in_code_block = True
                code_block_lang = code_match.group(1) or ""
            else:
                in_code_block = False
                code_block_lang = ""

        if len(current_chunk) + len(line) > max_length:
            if current_chunk:
                if in_code_block:
                    current_chunk += "\n```"
                chunks.append(current_chunk.strip())

                if in_code_block:
                    current_chunk = f"```{code_block_lang}\n{line}"
                else:
                    current_chunk = line
            else:
                while len(line) > max_length:
                    chunks.append(line[:max_length])
                    line = line[max_length:]
                current_chunk = line
        else:
            current_chunk += line

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks
