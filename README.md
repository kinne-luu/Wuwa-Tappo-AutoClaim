# Wuwa Tappo Auto Claim (Zani Edition) 🐱✨

[Tiếng Việt](#tiếng-việt) | [English](#english)

---

## Tiếng Việt

Công cụ tự động nhận rương thông minh cho **Wuwa Tappo** trên Windows với giao diện Fastfetch phong cách terminal hiện đại và hỗ trợ khay hệ thống (System Tray).

### ✨ Tính năng nổi bật
- **Fastfetch Terminal UI:** Giao diện trực quan, bảng màu pastel, thanh tiến trình mở rương, hiển thị chính xác mốc giờ gốc của server và độ trễ ngẫu nhiên (+jitter).
- **Tự động nhận diện Token / CID:** Tự động trích xuất an toàn từ WebView2 cookies hoặc bộ nhớ RAM của Wuwa Tappo.
- **Tự động phát hiện Game:** Quét thông minh qua tiến trình, Windows Registry và toàn bộ ổ đĩa máy tính, chạy trơn tru trên mọi máy khác nhau.
- **Cơ chế chống phát hiện:**
  - Khoảng thời gian trễ ngẫu nhiên (Jitter Delay) sau khi rương xuất hiện.
  - Giãn cách tối thiểu giữa 2 lần mở rương liên tiếp (`interval`).
  - Gia số click ngẫu nhiên mô phỏng người dùng thật.
- **Menu cài đặt nhanh [S]:** Bấm phím `[S]` ngay trong terminal để chọn và đổi riêng từng cài đặt mà không cần tắt app.
- **System Tray:** Thu nhỏ cửa sổ xuống khay hệ thống bằng phím `[H]` hoặc click nút thu nhỏ của Windows.

### 🚀 Hướng dẫn sử dụng
1. **Cài đặt thư viện (nếu chạy mã nguồn Python):**
   ```cmd
   pip install -r requirements.txt
   ```
2. **Khởi chạy:**
   - Nhấp đúp vào `run.bat` (tự động ưu tiên file `.exe` nếu có sẵn, hoặc chạy qua Python).
   - Hoặc chạy trực tiếp:
     ```cmd
     python app.py
     ```
3. **Tham số dòng lệnh (CLI):**
   ```cmd
   python app.py --status                          # Xem thông tin tài khoản rồi thoát
   python app.py --min-delay 5 --max-delay 30 --interval 15   # Tùy chỉnh độ trễ
   python app.py --tray                            # Khởi động ẩn ngay dưới khay hệ thống
   ```
4. **Phím tắt trong Terminal:**
   - `[H]`: Thu nhỏ xuống System Tray.
   - `[S]`: Mở menu cài đặt nhanh.
   - `[Q]`: Thoát an toàn.

5. **Đóng gói file .exe:**
   - Chạy `build.bat` để biên dịch thành file `WuwaTappoAutoClaim.exe`.

---

## English

An intelligent auto-claim tool for **Wuwa Tappo** on Windows featuring a clean Fastfetch-style terminal dashboard and System Tray support.

### ✨ Features
- **Fastfetch Terminal UI:** Clean aesthetic dashboard with pastel accents, progress bars, accurate server timestamp countdown, and separate jitter display.
- **Auto Token / CID Extraction:** Seamlessly extracts session tokens from WebView2 SQLite cookies or process memory.
- **Multi-Device Game Detection:** Detects `WuwaTappo.exe` across running processes, Windows Uninstall registry, and all physical drive letters.
- **Anti-Bot Mechanism:**
  - Randomized jitter delay after chests spawn.
  - Minimum cooldown interval between chest claims.
  - Dynamic delta clicks mimicking human activity.
- **Interactive Settings [S]:** Press `[S]` at runtime to open a numbered settings menu and adjust values without restarting.
- **System Tray Integration:** Press `[H]` or minimize window to hide the console into the system tray.

### 🚀 Getting Started
1. **Install dependencies:**
   ```cmd
   pip install -r requirements.txt
   ```
2. **Run:**
   - Double-click `run.bat`.
   - Or run with Python:
     ```cmd
     python app.py
     ```
3. **CLI Arguments:**
   ```cmd
   python app.py --status                          # Display account status & exit
   python app.py --min-delay 5 --max-delay 30 --interval 15   # Custom delays
   python app.py --tray                            # Start directly in system tray
   ```
4. **Terminal Hotkeys:**
   - `[H]`: Hide to System Tray.
   - `[S]`: Open Quick Settings menu.
   - `[Q]`: Quit gracefully.

5. **Build Standalone Binary:**
   - Run `build.bat` to compile `WuwaTappoAutoClaim.exe`.

---
**License:** MIT
