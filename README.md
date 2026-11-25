# WuwaTappo AutoClaim

<p align="center">
  <img src="UI Image/UI.png" alt="WuwaTappo AutoClaim UI" width="700">
</p>

[Tiếng Việt](#tiếng-việt) | [English](#english)

---

## Tiếng Việt

Tool tự động mở rương cho **Wuwa Tappo** trên Windows. Chạy gọn trong terminal hoặc thu xuống khay hệ thống, dùng được cả khi đang mở pet lẫn khi tắt pet.

### Tính năng chính
- Tự nhận tài khoản khi mở Wuwa Tappo, không cần nhập tay.
- Tự động mở 2 rương khi tới giờ, có độ trễ ngẫu nhiên cho tự nhiên.
- Hiện rõ món vừa mở được (**Character / Accessory / Emote**), độ hiếm và báo món mới (`[NEW]`) hay trùng (`[DUP]`).
- Hỗ trợ thông báo qua Discord Webhook.
- Chỉnh cài đặt và xem log trực tiếp khi đang chạy.

### Cách dùng
Tải `WuwaTappoAutoClaim.exe` ở mục [Releases](https://github.com/kinne-luu/Wuwa-Tappo-AutoClaim/releases) về chạy trực tiếp, hoặc chạy từ mã nguồn:

    pip install -r requirements.txt
    python app.py

Phím tắt trong cửa sổ tool:
- `H`: Thu xuống khay hệ thống
- `S`: Mở cài đặt (delay, khoảng cách giữa 2 rương, Discord Webhook, đường dẫn game)
- `L`: Xem log gần nhất
- `Q`: Thoát

Tham số dòng lệnh (nếu cần):
- `--status`: Xem nhanh thông tin tài khoản rồi thoát
- `--tray`: Mở ẩn dưới khay hệ thống
- `--min-delay` / `--max-delay` / `--interval`: Chỉnh nhanh độ trễ (giây)

---

## English

Auto chest claimer for **Wuwa Tappo** on Windows. Runs in the terminal or system tray, and works whether the desktop pet is open or closed.

### Features
- Automatically detects your account from Wuwa Tappo — no manual setup needed.
- Claims both chests on schedule with randomized delays.
- Shows what you got (**Character / Accessory / Emote**), rarity, and whether it's `[NEW]` or `[DUP]`.
- Optional Discord Webhook notifications.
- Change settings or check logs while running.

### Usage
Download `WuwaTappoAutoClaim.exe` from [Releases](https://github.com/kinne-luu/Wuwa-Tappo-AutoClaim/releases) and run it, or run from source:

    pip install -r requirements.txt
    python app.py

Hotkeys:
- `H`: Minimize to system tray
- `S`: Open settings (delays, chest interval, Discord Webhook, game path)
- `L`: View recent logs
- `Q`: Quit

CLI flags (optional):
- `--status`: Print account status and exit
- `--tray`: Start minimized in the system tray
- `--min-delay` / `--max-delay` / `--interval`: Set delays in seconds

---

**License:** MIT
