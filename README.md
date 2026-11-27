# WuwaTappo AutoClaim

<p align="center">
  <img src="UI Image/UI.png" alt="WuwaTappo AutoClaim Terminal UI" width="700">
</p>

[Tiếng Việt](#tiếng-việt) | [English](#english)

---

## Tiếng Việt

Tool autoclaim rương cho wuwa tappo, mấy ông có thể bật cả game cả tool mà ko lo bị lỗi.

### Tính năng
- Tự nhận tài khoản đang đăng nhập trong Wuwa Tappo, không cần lấy thông tin thủ công.
- Tự canh giờ mở cả 2 rương với độ trễ ngẫu nhiên.
- Có chế độ autocfarm khi máy để không, chạm lại chuột hoặc bàn phím là tự dừng.
- Xem tiến, lịch sử nhận rương và gửi thông báo qua Discord (nếu mấy ông bật discord webhook).
- Đổi cài đặt ngay khi đang chạy, không cần tắt mở lại.

### Cách dùng
Tải sẵn file `.exe` trong mục Releases về chạy luôn, hoặc nếu chạy bằng mã nguồn thì cài thư viện trước:

    pip install -r requirements.txt

Chạy bằng `run.bat` (ưu tiên file `.exe` nếu có, không thì chạy Python), hoặc:

    python app.py

Một số tham số chạy kèm:

    python app.py --status
    python app.py --min-delay 5 --max-delay 30 --interval 15
    python app.py --tray
    python app.py --idle-farm

- `--status`: xem nhanh thông tin tài khoản rồi thoát
- `--min-delay`, `--max-delay`, `--interval`: chỉnh độ trễ mở rương (giây)
- `--tray`: khởi động ẩn luôn dưới khay hệ thống
- `--idle-farm`: bật sẵn tự tích điểm khi máy rảnh

Phím tắt trong terminal: `F` bật/tắt tích điểm khi rảnh, `T` xem thống kê, `S` cài đặt, `L` xem log, `H` thu xuống khay, `Q` thoát.

Muốn tự đóng gói thành `.exe` thì chạy `build.bat`, file tạo ra là `WuwaTappoAutoClaim.exe`.

---

## English

Chest auto-claim tool for Wuwa Tappo — you can run both the game and the tool at the same time without worrying about errors.

### Features
- Automatically detects your logged-in Wuwa Tappo account, no manual setup required.
- Automatically times and opens both chests with random delays.
- Includes an auto-farm mode when your PC is idle; stops automatically as soon as you move the mouse or press a key.
- View progress, chest claim history, and send notifications via Discord (if you enable Discord webhook).
- Change settings on the fly while running, no restart needed.

### Usage
Download the pre-built `.exe` from Releases and run it right away, or if running from source, install the dependencies first:

    pip install -r requirements.txt

Run via `run.bat` (prioritizes the `.exe` if available, otherwise runs Python), or:

    python app.py

Some optional launch arguments:

    python app.py --status
    python app.py --min-delay 5 --max-delay 30 --interval 15
    python app.py --tray
    python app.py --idle-farm

- `--status`: quickly view account info and exit
- `--min-delay`, `--max-delay`, `--interval`: adjust chest opening delays (seconds)
- `--tray`: start minimized in the system tray
- `--idle-farm`: enable auto point farming when idle on startup

Terminal hotkeys: `F` toggle idle point farming, `T` view stats, `S` settings, `L` view logs, `H` hide to tray, `Q` quit.

If you want to build the `.exe` yourself, run `build.bat` — the output file will be `WuwaTappoAutoClaim.exe`.

---

**License:** MIT
