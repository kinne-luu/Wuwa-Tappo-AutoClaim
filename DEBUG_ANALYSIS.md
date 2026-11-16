# KẾT QUẢ ĐỐI CHIẾU & PHÂN TÍCH LỖI: WUWA TAPPO AUTO CLAIM
**Mã lỗi ghi nhận:** `[70003] Invalid client point count` & `[80022] Server is busy`

---

## 1. Bối cảnh & Mô tả hiện tượng (Problem Description)
* **Ứng dụng chính:** Wuwa Tappo (Desktop Pet game của Kuro Games - Wuthering Waves). Bản chất là ứng dụng Desktop đóng gói Web bằng Microsoft Edge WebView2 (Front-end viết bằng Vue.js + Pinia Store, Back-end gọi API HTTPS của Kuro Games).
* **Công cụ Auto Claim:** Được phát triển dựa trên reverse engineering API của repo gốc `Triet2804Dev/Wuwa-Tappo-Auto-Claim` (chạy Python/PyInstaller console exe).
* **Hiện tượng:**
  1. Khi **tắt hoàn toàn** con Pet Wuwa Tappo và chỉ để Tool chạy ngầm: Tool hoạt động rất tốt 100%, tự tính toán cooldown 30 phút, gửi request claim rương lên Kuro Server thành công, nhận thưởng và cộng click bình thường (`SUCCESS: Claimed Chest #1 & #2`).
  2. Khi **bật đồng thời cả con Pet Wuwa Tappo trên desktop và Tool Auto Claim**:
     - Tool vẫn gửi claim thành công trên Server Kuro.
     - Nhưng trên cửa sổ con Pet ngoài màn hình: Khi người dùng bấm tay hoặc con Pet tự đồng bộ, màn hình game lập tức hiện pop-up lỗi:
       - `Invalid client point count. [70003:<hash>]`
       - `Server is busy [80022]`
     - Khởi động lại con Pet thì con Pet mới hiển thị trạng thái "Đã nhận".

---

## 2. Luồng hoạt động & Cơ chế kỹ thuật (Technical Flow)

### A. Cơ chế gửi request của Tool khi nhận rương:
Endpoint máy chủ Kuro Games:
`POST https://api-wutheringwaves-wuwatappo.kurogames-global.com/api/frontend/chests/open`

Payload:
```json
{
  "place": "left",
  "click_num": 816268
}
```
* Khi mở rương, server bắt buộc tiêu tốn `1,000` click (`CHEST_COST`).
* Tool bù đắp click bằng công thức:
  `target_click = total_clicks + CLICK_GAIN_PER_CHEST (1000)`
* Sau khi nhận rương, server Kuro ghi nhận tài khoản đã đạt số click `816,268`.

### B. Cơ chế của con Pet Wuwa Tappo trên Desktop:
* Con Pet là một cửa sổ WebView2 độc lập, lưu biến trạng thái điểm trong RAM (Pinia store `userInfo.total_click_count`).
* Con Pet tự sinh điểm nội bộ khi idle hoặc khi người dùng click chuột.
* Định kỳ, con Pet gửi request đồng bộ số click trong RAM của nó lên server.

---

## 3. Bản chất nguyên nhân gây lỗi (Root Cause Analysis)

1. **State Desynchronization (Lệch trạng thái Click Client - Server):**
   - Tool gửi thẳng lên Server điểm mới (`816,268`).
   - Nhưng WebView2 của con Pet trên màn hình không biết điều này, RAM của con Pet vẫn giữ con số cũ (ví dụ `814,000`).
   - Khi người dùng click tay vào Pet hoặc Pet tự động gửi sync: Con Pet gửi `814,000` lên Server $\rightarrow$ Server Kuro phát hiện điểm client gửi lên bị thụt lùi so với điểm hiện tại trên Server $\rightarrow$ Server văng lỗi **`[70003] Invalid client point count`**.

2. **Xung đột tần suất request (Rate Limiting / Server Busy):**
   - Khi con Pet bị văng lỗi lệch điểm, nó liên tục gửi retry polling request lên Server Kuro để kéo lại state.
   - Đúng lúc này Tool cũng đang gửi request kiểm tra hoặc claim rương $\rightarrow$ Server Kuro phát hiện 2 client cùng gửi request dồn dập trên 1 CID/Token $\rightarrow$ Server trả về **`[80022] Server is busy`**.

---

## 4. Các giải pháp đã thử nghiệm & Kết quả

| Giải pháp | Cách thực hiện | Kết quả thực tế | Lý do thất bại |
| :--- | :--- | :--- | :--- |
| **Thử nghiệm 1:** Giãn cách rương | Thêm delay ép buộc `time.sleep(10)` giữa 2 rương | Thành công khi Pet đóng | Chỉ giải quyết được rate-limit của Tool, không giải quyết được lệch điểm giữa Pet và Server. |
| **Thử nghiệm 2:** Tắt Pet khi chạy | Chạy thuần 100% API (100% API-Driven) | **Thành công 100%** | Người dùng không ngắm được con Pet trên desktop khi tool chạy. |
| **Thử nghiệm 3:** Chrome DevTools Protocol (CDP Sync) | Bật cổng `--remote-debugging-port=19222`, dùng WebSocket inject JS `store.$patch` vào Pinia | **Thất bại** | Cổng 19222 không lắng nghe (ConnectTimeout). Wuwa Tappo là app đóng gói WebView2 đặc thù, cờ môi trường hoặc registry không ép được WebView2 mở remote debugging port mà không có quyền/flag tương thích từ launcher. |
| **Thử nghiệm 4:** Xin quyền Administrator | Thêm `ensure_admin()` gọi UAC `runas` | Vẫn lỗi | Dù có quyền Admin, cổng CDP vẫn không mở được trên WebView2 của game, Pet và Server vẫn bị lệch điểm. |

---

## 5. Câu hỏi tham vấn dành cho Model lớn hơn (Key Questions)

1. **Làm thế nào để ứng dụng Desktop WebView2 của Wuwa Tappo tự động cập nhật số điểm từ Server mà không bị lỗi `[70003]` khi có một tiến trình ngầm thứ hai can thiệp vào API?**
   - Game có endpoint nào để kích hoạt client fetch lại dữ liệu người dùng (`/api/frontend/user/me`) mà không bị coi là invalid click không?
   - Có cách nào can thiệp an toàn vào bộ nhớ tiến trình (Memory Write qua `WriteProcessMemory`) để đồng bộ lại con số `total_click_count` trong RAM của con Pet thay vì dùng CDP?

2. **Cơ chế tính toán click của máy chủ Kuro Games:**
   - Tại sao request claim rương bắt buộc phải truyền kèm `click_num`?
   - Nếu Tool gửi `click_num = total_clicks` (không cộng thêm điểm) hoặc truyền đúng bằng số điểm hiện tại mà không sửa đổi, liệu Pet trên desktop có bị lỗi `70003` hay không?

3. **Giải pháp kiến trúc nào tối ưu nhất để vừa giữ Pet hiển thị trên màn hình vừa để bot tự claim rương?**
