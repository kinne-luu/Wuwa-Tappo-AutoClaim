# WuwaTappo AutoClaim

<p align="center">
  <img src="UI Image/UI.png" alt="WuwaTappo AutoClaim Terminal UI" width="700">
</p>

[Tiếng Việt](#tiếng-việt) | [English](#english)

---

## Tiếng Việt

Tool tự động nhận rương cho **Wuwa Tappo** trên Windows. Chạy trong terminal, có thể thu xuống khay hệ thống, dùng chung được lúc đang mở pet trên màn hình mà không bị văng lỗi.

### Tính năng
- Tự nhận tài khoản đang đăng nhập trong Wuwa Tappo, không cần lấy thông tin thủ công.
- Tự canh giờ mở cả 2 rương với độ trễ ngẫu nhiên, báo rõ món nhận được là mới hay trùng.
- Có chế độ tự gõ tích điểm khi máy để không, chạm lại chuột hoặc bàn phím là tự dừng.
- Xem tiến độ sưu tập, lịch sử nhận rương và gửi thông báo qua Discord (nếu bật).
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

Auto-claim tool for **Wuwa Tappo** on Windows. Runs in the terminal, minimizes to the system tray, and works alongside the desktop pet without causing errors.

### Features
- Picks up your logged-in account from Wuwa Tappo automatically.
- Opens both chests on time with random delays and shows whether drops are new or duplicates.
- Optional idle click farming when you're away from the PC (stops right away when you move the mouse or type).
- Tracks collection progress, drop history, and supports Discord notifications.
- Change settings on the fly without restarting.

### Usage
Grab the `.exe` from Releases, or install dependencies if running from source:

    pip install -r requirements.txt

Run with `run.bat` (uses the `.exe` if present, otherwise Python), or:

    python app.py

Optional arguments:

    python app.py --status
    python app.py --min-delay 5 --max-delay 30 --interval 15
    python app.py --tray
    python app.py --idle-farm

- `--status`: show account info and exit
- `--min-delay`, `--max-delay`, `--interval`: adjust claim delays (seconds)
- `--tray`: start minimized in the system tray
- `--idle-farm`: enable idle click farming on startup

Hotkeys in the terminal: `F` toggle idle farm, `T` stats, `S` settings, `L` logs, `H` hide to tray, `Q` quit.

To build a standalone `.exe`, run `build.bat`. The output is `WuwaTappoAutoClaim.exe`.

---

**License:** MIT
