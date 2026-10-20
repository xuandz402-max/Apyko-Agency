# Apyko Agency — bản deploy lên hosting

Web app quản lý dành cho Apyko Agency: nghiên cứu sản phẩm Shopee (tính lợi nhuận,
chấm điểm cơ hội), Apyko Uni (58 bài học nội bộ), quản lý tài khoản nhân sự có
phân quyền. Chạy bằng Python + FastAPI + SQLite, đóng gói Docker — deploy 1 lần,
lấy link gửi nhân sự đăng nhập.

## GMV Max Shopee

Theo dõi chỉ số quảng cáo Shopee (GMV Max) theo ngày, từng sản phẩm — thay cho
file Google Sheet "THEO DÕI CHỈ SỐ QUẢNG CÁO SẢN PHẨM".

- Sidebar **GMV Max Shopee**: mỗi sản phẩm là một tab (như một sheet trong file).
- Nhân sự nhập tay: ngày, lượt xem, click, chuyển đổi, doanh thu (RM), chi phí QC,
  ghi chú quyết định. Các cột CTR / CIR / CPC / CR / AOV / ROAS / quy đổi VND do
  **máy chủ tự tính** (VND = RM x 5300; chia cho 0 hiển thị "—").
- Bảng **tự động đồng bộ mỗi 10 giây** (polling) — ai sửa thì mọi người thấy ngay,
  không cần F5. Mỗi dòng ghi tên người nhập cuối cùng.
- Phân quyền như các trang khác: xem → nhập/sửa → xóa, kiểm tra ở máy chủ.
- Lần khởi động đầu (bảng trống): tự tạo sẵn 5 sản phẩm từ sheet thật của shop
  (ỐC NỞ CAMP MỚI, LIỀM, XÀ BÔNG NGHỆ, ĐEN TÓC, MẶT NẠ ĐỊNH HÌNH), sheet trống để
  nhập liệu. Đổi tên/xóa/thêm sản phẩm tự do trong app.

## 📊 Biểu đồ GMV + cảnh báo tự động

Khu vực mới trên trang **GMV Max Shopee** (phía trên bảng số liệu):

- **Biểu đồ đường GMV + Chi phí QC (VND)** và **biểu đồ ROAS** theo ngày, vẽ
  bằng SVG + JS thuần trong trang (không thư viện ngoài). Chọn sản phẩm
  (Tất cả / từng sản phẩm) và khoảng 7 / 14 / 30 ngày (mặc định 14).
- **Ngày không có số liệu được để TRỐNG** trên biểu đồ và bảng số đi kèm
  (None), tuyệt đối không điền 0 — tránh hiểu nhầm "chưa nhập số / không
  chạy quảng cáo" thành "chạy mà không ra GMV". ROAS ngày = tổng GMV /
  tổng chi phí của ngày đó; chi phí 0 thì ROAS cũng để trống.
- **Biểu đồ cột tổng GMV theo sản phẩm** trong kỳ (chỉ tính sản phẩm có số
  liệu trong kỳ), kèm chi phí và ROAS tổng.
- **Cảnh báo tự động** (hiển thị ngay trên trang + đẩy vào mục Thông báo
  trong app), dùng chung ngưỡng với Dashboard CEO (`app/ceo.py`):
  1. `roas_low` — ROAS của ngày có số mới nhất của sản phẩm < **2.0**
     (`ROAS_WARN`).
  2. `stale` — sản phẩm không có số liệu trong **3 ngày** gần nhất
     (`STALE_DAYS`), kể cả chưa từng nhập số.
  3. `gmv_drop` — tổng GMV 3 ngày-có-số gần nhất giảm > **30%**
     (`DROP_PCT`) so với tối đa 3 ngày-có-số liền trước.
  4. `roas_drop` — ROAS (tổng GMV / tổng chi phí) của 2 cửa sổ trên giảm
     tương đối > **30%**.
  Quy tắc 3–4 chỉ tính khi sản phẩm có tối thiểu 4 ngày-có-số và cửa sổ
  trước có doanh thu / chi phí > 0.
- **Người nhận thông báo**: chủ shop + mọi tài khoản đang hoạt động có
  quyền xem GMV (module GMV dùng chung quyền `can_view_products` — chính
  là quyền gác trang `/gmv` và API GMV). Thông báo dùng chung bảng
  `notifications` với Daily Checklist (tiêu đề "⚠️ Cảnh báo GMV Max: …",
  link về `/gmv`).
- **Chống spam**: khóa dedupe `gmv:{product_id}:{rule}:{YYYY-MM-DD}` lưu
  ở bảng phụ trợ `gmv_alert_log` — mỗi (sản phẩm, quy tắc) tối đa **1
  thông báo mỗi ngày** cho mỗi người nhận, dù scheduler nền (tick 60 giây)
  và lưới an toàn khi mở trang `/gmv` chạy lại bao nhiêu lần. Sang ngày
  mới, cảnh báo còn đúng thì được báo lại.
- Màu biểu đồ theo theme đen/trắng/xám: đường GMV tím **#7C3AED** (màu
  logo), chi phí xám, ROAS đen, đường ngưỡng ROAS đỏ đứt nét.

## Báo cáo ngày

Nhân sự nhập doanh thu + chi phí mỗi ngày, xuất ảnh PNG gửi Zalo cho khách.

- Sidebar **Báo cáo ngày**: form nhập theo ngày — doanh thu 5 nguồn (Thẻ sản phẩm,
  Live, Video, Tiếp thị liên kết, Affiliate), GMV quảng cáo, chi phí ads, giá trị
  đơn trung bình, tỉ lệ chuyển đổi (%), ghi chú. Mỗi ngày 1 báo cáo; nhập trùng
  ngày thì cập nhật.
- **Tổng doanh thu** và **ROAS** do **máy chủ tự tính** (chia cho 0 hiển thị "—").
- Mỗi dòng có nút **Xuất ảnh**: vẽ thẻ báo cáo 1080x1500px lên canvas (không cần
  thư viện ngoài) rồi tải file `apyko-bao-cao-YYYY-MM-DD.png` — header cam nghệ,
  đủ 5 nguồn doanh thu, khối hiệu quả quảng cáo, footer giờ xuất.
- Phân quyền như các trang khác: xem → nhập/sửa → xóa, kiểm tra ở máy chủ.

## Daily Checklist

Checklist vận hành Shopee đầu ngày (20 việc mẫu, 6 nhóm: Tình trạng shop ·
Đơn hàng · Tin nhắn & đánh giá · Tồn kho & sản phẩm · Voucher & khuyến mãi ·
Quảng cáo & báo cáo) với nhắc hạn tự động trong giờ làm việc.

- **Trang của tôi** (sidebar **Daily Checklist**): việc của ngày (mặc định hôm
  nay, đổi ngày được), nhóm theo nhóm việc, có hạn chót, ô ghi chú và nút
  Hoàn thành / Mở lại / Hủy.
- **Màu trạng thái riêng của module** (không theo theme chung): sắp tới hạn =
  đỏ trên nền hồng nhạt; quá hạn = đỏ đậm + nhãn **QUÁ HẠN**; hoàn thành =
  xanh lá; đã hủy = xám, gạch ngang.
- **Bảng Leader** (`/checklist/board`): tổng việc, đã xong, chưa xong, quá
  hạn, % hoàn thành theo từng nhân viên; bấm tên nhân viên để xem việc của họ.
- **Quản trị mẫu** (`/checklist/admin`): bật/tắt/sửa mẫu việc, phân công mặc
  định, quản lý shop, cài đặt giờ làm việc (mặc định 08:00–17:30, Thứ 2–Thứ 7),
  chu kỳ nhắc lại khi quá hạn (mặc định 30 phút) và ngưỡng "sắp tới hạn"
  (mặc định 30 phút).
- **Cơ chế nhắc**: một luồng nền kiểm tra mỗi 60 giây (tắt bằng
  `DISABLE_BACKGROUND=1`); ngoài ra mỗi lần mở trang checklist/thông báo,
  app cũng kiểm tra lại (idempotent). Đến hạn → gửi 1 thông báo; quá hạn →
  nhắc lại theo chu kỳ chỉ trong giờ làm việc. Việc đã hoàn thành/đã hủy
  ngừng nhắc. Chống gửi trùng bằng điều kiện cập nhật có guard trên
  `last_reminder_at`/`due_notified_at`. Thông báo xem ở sidebar **Thông báo**
  (chuông có số chưa đọc).
- **Phân quyền** (kiểm tra ở máy chủ): Chủ shop = toàn quyền; **Leader
  checklist** = xem tất cả + bảng thống kê + phân công; **Quản trị
  checklist** = mẫu việc/shop/cài đặt; nhân viên thường chỉ thấy và xử lý
  việc được giao cho mình. Hai quyền mới cấp ở trang **Tài khoản**.

## Dashboard CEO

Trang **👑 Dashboard CEO** (sidebar, ngay dưới Dashboard, đường dẫn `/ceo`)
gom số thật của cả ngày hiện tại (giờ Việt Nam) vào 1 màn hình — không có
bảng dữ liệu riêng, chỉ đọc tổng hợp từ các module khác:

- **Doanh thu hôm nay** — từ **Báo cáo ngày**: tổng doanh thu (5 nguồn) hôm
  nay, kèm % tăng/giảm so với hôm qua (hôm qua = 0 hoặc chưa nhập thì không
  hiện %); chưa nhập báo cáo thì thẻ hiện "Chưa nhập".
- **Chi phí ads hôm nay + ROAS** — cũng từ Báo cáo ngày của hôm nay.
- **GMV quảng cáo hôm nay** — tổng các dòng GMV Max có ngày = hôm nay:
  doanh thu RM quy đổi VNĐ (RM x 5300), chi phí quy đổi và ROAS chung.
- **Checklist hôm nay** — từ **Daily Checklist**: đã xong / tổng việc, %
  hoàn thành và số việc quá hạn.
- **⚠️ Cần chú ý** — cảnh báo gộp: nhân viên còn việc quá hạn (bấm vào xem
  việc của họ); sản phẩm GMV có ROAS thấp hoặc lâu chưa có dữ liệu; chưa
  nhập Báo cáo ngày hôm nay.
- **Bảng Nhân viên hôm nay** — được giao / đã xong / quá hạn / % hoàn thành
  từng nhân viên; bấm tên để mở checklist của nhân viên đó.
- **Bảng Doanh thu 7 ngày** — ngày nào chưa nhập báo cáo hiện "—" (không
  tính là 0).
- **Đồng hồ ngày giờ** — đầu trang hiện ngày giờ Việt Nam hiện tại, tự cập
  nhật mỗi 30 giây.
- **📈 So sánh theo kỳ** — 4 thẻ Doanh thu / Chi phí quảng cáo / ROAS / GMV
  quảng cáo VNĐ của kỳ hiện tại kèm **% thay đổi so với kỳ trước**, có nút
  chuyển **Ngày / Tuần / Tháng** (mặc định Ngày). Cách so kỳ: **Ngày** =
  hôm nay vs hôm qua; **Tuần** = thứ Hai -> hôm nay vs cùng số ngày đầu
  tuần trước (VD 19/10 – 20/10 vs 12/10 – 13/10); **Tháng** = ngày 1 ->
  hôm nay vs cùng số ngày đầu tháng trước (tháng trước ngắn hơn thì dừng ở
  ngày cuối của tháng trước). Hai khoảng luôn dài bằng nhau và giao diện
  ghi rõ nhãn khoảng ngày. **Tăng hiện màu xanh lá #15803D kèm ▲ và dấu +,
  giảm hiện màu đỏ #DC2626 kèm ▼** — đây là ngoại lệ màu duy nhất ngoài
  theme đen trắng, do chủ shop chốt riêng cho số tăng/giảm. Kỳ trước = 0
  hoặc thiếu dữ liệu thì hiện "—", không bịa %.
- **📊 Biểu đồ doanh thu 30 ngày gần nhất** — biểu đồ cột doanh thu từng
  ngày (SVG vẽ bằng JS thuần); ngày chưa nhập Báo cáo ngày được để trống,
  không vẽ 0.

Ngưỡng cảnh báo mặc định (chỉnh trong `app/ceo.py`): `ROAS_WARN = 2.0`
(entry GMV mới nhất của sản phẩm có ROAS dưới 2.0 thì cảnh báo) và
`STALE_DAYS = 3` (sản phẩm không có entry nào trong 3 ngày gần nhất thì
cảnh báo "chưa có dữ liệu gần đây").

**Ai xem được** (kiểm tra ở máy chủ): chủ sở hữu, hoặc tài khoản có quyền
**Leader checklist** / **Quản trị checklist**. Nhân viên thường bị chặn
(HTTP 403) và không thấy mục này trong sidebar.

**Tốc độ:** số liệu trang này được nhớ tạm (cache) trong bộ nhớ máy chủ
**60 giây** (hàm `cached_overview` trong `app/ceo.py`) vì trang chỉ đọc —
sửa dữ liệu ở các module khác (Báo cáo ngày, GMV Max, checklist...) có thể
mất tối đa ~1 phút mới hiện lên trang CEO. Các trang còn lại không dùng
cache này. Khu so sánh theo kỳ và biểu đồ 30 ngày cũng cache 60 giây
tương tự (`cached_period_compare` khoá theo ngày + kỳ, và
`cached_revenue_series`).

## 🗓️ Chọn khoảng thời gian + so sánh kỳ (dùng chung)

Các trang **có dữ liệu theo thời gian** dùng chung một thanh chọn kỳ
(**Ngày / Tuần / Tháng / Tự chọn** từ ngày – đến ngày) và cùng một cách so
sánh với **kỳ liền trước dài bằng nhau** — logic ở `app/periods.py`
(`resolve_period`, `delta_pct`), giao diện ở `templates/_period_bar.html`
(macro `period_bar` + `per_metric_card`), CSS tiền tố `per-`:

- **Ngày** = hôm nay vs hôm qua. **Tuần** = thứ Hai -> hôm nay vs cùng số
  ngày đầu tuần trước. **Tháng** = ngày 1 -> hôm nay vs cùng số ngày đầu
  tháng trước (tháng trước ngắn hơn thì dừng ở cuối tháng trước) — đúng
  công thức của Dashboard CEO (`ceo.period_ranges`). **Tự chọn** =
  khoảng [from, to] người dùng nhập; kỳ trước là khoảng dài bằng nó nằm
  ngay trước ngày bắt đầu. Param sai (period lạ, ngày sai định dạng,
  to < from) tự quay về **Ngày**, không văng lỗi.
- **Delta**: % thay đổi = (kỳ này − kỳ trước) / kỳ trước × 100, làm tròn
  0,1. Kỳ trước = 0 hoặc thiếu dữ liệu -> hiện **"—"**, không bịa %. Tăng
  hiện **xanh lá #15803D kèm ▲**, giảm hiện **đỏ #DC2626 kèm ▼** (class
  `.delta-up` / `.delta-down`) — ngoại lệ màu cho số tăng/giảm như
  Dashboard CEO.
- **Trang Báo cáo ngày** (`/bao-cao?period=&from=&to=`): danh sách báo
  cáo lọc theo kỳ hiện tại + thẻ **Tổng theo kỳ** (tổng doanh thu qua
  `calc_daily`, tổng chi phí ads, ROAS kỳ = tổng GMV ads / tổng chi phí
  ads của cả kỳ, số ngày có báo cáo). Ngày trong kỳ chưa nhập báo cáo thì
  bỏ qua, không tính là 0; cả kỳ chưa có báo cáo thì hiện thông báo nhẹ.
  Mặc định là kỳ Ngày (chỉ hôm nay).
- **Trang GMV Max** (`/gmv`): thêm dải **📈 So sánh theo kỳ** riêng —
  GMV (VNĐ), Chi phí (VNĐ), ROAS của kỳ + delta — dùng `?period=&from=&to=`
  **độc lập** với `?product=&days=` của biểu đồ (chuyển kỳ vẫn giữ nguyên
  sản phẩm/khoảng ngày đang chọn ở biểu đồ). Số liệu là tổng mọi sản phẩm
  theo ngày của dòng dữ liệu, VNĐ = RM × 5.300; kỳ không có entry nào thì
  các chỉ số hiện "—".
- **Bảng Leader checklist** (`/checklist/board`): kỳ tính quanh **ngày
  neo** (ô Ngày ở bộ lọc như cũ). Khi kỳ dài hơn 1 ngày, bốn thẻ số, %
  hoàn thành và cả bảng theo nhân viên đều là **tổng gộp của cả kỳ**
  (`checklist.board_range_stats` cộng dồn `board_stats` từng ngày,
  per-user gộp theo nhân viên và tính lại % trên tổng — không lấy trung
  bình % ngày). % hoàn thành kèm **delta theo ĐIỂM %** (hiệu 2 tỷ lệ)
  so với kỳ trước. Khoảng bị **chặn tối đa 31 ngày** (`periods.cap_period`
  giữ 31 ngày gần nhất và ghi chú trên trang) vì phải cộng dồn từng ngày.
  Link "xem chi tiết" của nhân viên mở ngày cuối kỳ.

Các trang **không** có thanh kỳ vì dữ liệu không gắn với thời gian vận
hành: Định giá (bảng tính giá tại thời điểm nhập), Sản phẩm/Phân tích
(danh mục SKU), Apyko Uni (bài học), Dashboard chủ (tổng quan sản phẩm).
Dashboard CEO có thanh Ngày/Tuần/Tháng riêng từ trước (cùng công thức,
chưa có Tự chọn).

## 🏷️ Định giá sản phẩm

Trang `/dinh-gia` — bảng tính giá bán Shopee bám đúng file Excel **"Dự tính giá
bán"** của chủ shop (sheet "Tính hàng loạt" + "Tham số mặc định"; đã đối chiếu
từng khoản phí với 3 dòng mẫu trong file, sai số ≤ 1đ).

- **Ngành hàng**: 2.904 ngành (1.452 [Thường] + 1.452 [MALL]) đóng gói sẵn tại
  `app/data/pricing_categories.json` (sinh từ sheet "Ngành hàng" bằng
  `hidden_files/gen_pricing_categories.py`). Gõ tìm ngành → chọn → app tự điền
  % phí ngành; không cần mạng ngoài.
- **Công thức** (P = giá bán, E = giá vốn): Phí ngành = P × %ngành ·
  Phí thanh toán = P × %thanh toán · Phí Voucher Xtra = MIN(P × %voucher, trần) ·
  Phí Affiliate = P × %affiliate · Quảng cáo = P × %% quảng cáo ·
  Thuế = P × %thuế · Phí cố định/đơn = Pi Ship + Hạ tầng.
  **Tổng chi phí = E + tất cả các khoản trên; Lãi/Lỗ = P − Tổng chi phí;
  % biên lãi = Lãi/Lỗ ÷ P** (P = 0 → hiển thị "—").
- **Tham số mặc định** (bảng `pricing_settings`, seed từ sheet "Tham số mặc
  định"): Phí thanh toán 6%, Voucher Xtra 0% (shop tự điền 5,5% nếu có đăng ký),
  trần Voucher 50.000đ/sp, Affiliate 0%, Pi Ship 2.700đ/đơn, Hạ tầng 3.000đ/đơn,
  Thuế khấu trừ 1,5% (1% VAT + 0,5% TNCN). Sửa tại khu "Tham số mặc định" cuối
  trang — **chỉ chủ sở hữu / Quản trị checklist** (kiểm tra ở backend); sản phẩm
  tạo mới sẽ dùng mặc định mới, từng dòng vẫn sửa riêng được.
- **Tính ngược**: nhập giá vốn + ngành + % lãi mong muốn → app tìm giá bán
  nguyên đồng nhỏ nhất đạt biên lãi đó (tìm kiếm nhị phân vì phí Voucher có
  trần MIN) và hiện bảng phân bổ phí tại giá đó. Không lưu.
- **Phân quyền**: đã đăng nhập là xem + tính ngược được; thêm/sửa cần quyền
  **Thêm & sửa dữ liệu**, xóa cần quyền **Xóa dữ liệu** (giống module Sản phẩm).
  Có nút **Xuất CSV** kèm đầy đủ các cột đã tính.
- Quy ước %: API/giao diện dùng số % kiểu người dùng (6 = 6%); DB lưu thập phân
  (0.06) như file gốc; chuyển đổi nằm ở một chỗ duy nhất trong `app/pricing.py`.

## Tối ưu tốc độ (gói free)

- **Nén GZip** mọi response ≥ 1KB (`GZipMiddleware` trong `app/main.py`).
- File tĩnh (`/static/*`) được gắn `Cache-Control: public, max-age=600` —
  trình duyệt lưu 10 phút, chuyển trang không tải lại CSS. Không đặt lâu
  hơn để tránh dính giao diện cũ sau mỗi lần deploy.
- Mỗi trang HTML chỉ hỏi database ít vòng nhất có thể: dữ liệu dùng chung
  trong 1 request (danh sách nhân viên, shop...) được query 1 lần rồi dùng
  lại; trang CEO nạp báo cáo ngày/GMV bằng 1 query cho mọi ngày/sản phẩm.
- **Lưới an toàn của Daily Checklist** (tự tạo việc + gửi nhắc khi mở
  trang) bị giới hạn tối đa 1 lần / 60 giây cho toàn tiến trình — scheduler
  nền vẫn tick mỗi 60 giây làm cùng việc đó, lưới an toàn chỉ là dự phòng
  nên nhắc hạn có thể chậm tối đa ~60 giây nhưng mở trang nhẹ đi nhiều.

## Tài khoản & bảo mật

- **Lần chạy đầu tiên:** mở trang `/setup` để tạo tài khoản **chủ sở hữu**
  (hoặc đặt sẵn `OWNER_USERNAME` / `OWNER_PASSWORD` trong biến môi trường).
- Chủ sở hữu vào **Quản lý tài khoản** để tạo tài khoản nhân sự → hệ thống sinh
  **mã kích hoạt** → gửi mã cho nhân sự → họ vào trang **Kích hoạt** nhập mã 1 lần
  và tự đặt mật khẩu.
- Phân quyền từng tài khoản: xem sản phẩm, thêm/sửa, xóa, xem Apyko Uni.
  Người không có tài khoản chỉ thấy màn hình đăng nhập — không xem được gì.
- Mọi kiểm tra quyền thực hiện ở tầng server. Đặt `SECRET_KEY` thật khi deploy.

## Chạy thử trên máy (Windows)

```powershell
cd APYKO-AGENCY-DEPLOY
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = "chuoi-bi-mat-cua-ban"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Mở http://127.0.0.1:8000 → trang `/setup` tạo tài khoản chủ sở hữu.

## Deploy lên Render (miễn phí, dễ nhất)

1. Đẩy thư mục này lên GitHub (tạo repo mới, upload toàn bộ file).
2. Vào https://dashboard.render.com → **New +** → **Web Service** → chọn repo.
3. Mục **Runtime**: chọn **Docker** (Render tự nhận Dockerfile).
4. Mục **Environment Variables** → **Add** từng biến:
   - `SECRET_KEY` = một chuỗi ngẫu nhiên thật dài (tự nghĩ ra, giữ bí mật)
   - `OWNER_USERNAME` = tên đăng nhập của bạn, ví dụ `chushop`
   - `OWNER_PASSWORD` = mật khẩu của bạn (ít nhất 8 ký tự)
   - `COOKIE_SECURE` = `true`
5. Bấm **Create Web Service** → chờ 3–5 phút cho build xong.
6. Render cấp cho bạn 1 link dạng `https://apyko-agency.onrender.com` — mở link,
   đăng nhập bằng tài khoản chủ sở hữu vừa đặt.
7. Vào **Quản lý tài khoản** tạo tài khoản cho từng nhân sự, gửi link + mã kích
   hoạt cho họ.

> **Lưu ý gói miễn phí:** Render tắt máy khi không ai dùng 15 phút nên lần mở
> đầu có thể chờ ~30 giây để máy khởi động lại. Dữ liệu SQLite nằm trên ổ đĩa
> tạm — nếu deploy lại code, dữ liệu có thể mất: hãy làm theo mục
> **Database online (Turso)** bên dưới để giữ dữ liệu vĩnh viễn (miễn phí).
> Tạm thời chưa làm thì **xuất CSV sản phẩm định kỳ** (nút Xuất CSV ở trang
> Sản phẩm) để sao lưu.

## Deploy lên Railway

1. https://railway.app → New Project → **Deploy from Repo** → chọn repo GitHub.
2. Railway tự nhận Dockerfile. Vào service → **Variables**, thêm:
   `SECRET_KEY`, `OWNER_USERNAME`, `OWNER_PASSWORD`, `COOKIE_SECURE=true`.
3. Tab **Settings** → **Networking** → **Generate Domain** để lấy link.
4. Railway cũng có ổ đĩa tạm như Render — sao lưu CSV định kỳ.

## Deploy lên Fly.io

1. Cài `flyctl`, đăng nhập: `fly auth login`.
2. Trong thư mục này: `fly launch` (chọn region gần VN: `sin` Singapore).
3. Đặt biến môi trường:
   ```
   fly secrets set SECRET_KEY="chuoi-bi-mat-that-dai" OWNER_USERNAME="chushop" OWNER_PASSWORD="mat-khau-cua-ban" COOKIE_SECURE="true"
   ```
4. `fly deploy` → `fly open` để lấy link.
5. Muốn giữ dữ liệu: `fly volumes create apyko_data --size 1` rồi gắn vào
   `/srv/data` trong `fly.toml`.

## Database online (Turso) — chống mất dữ liệu khi deploy

Mặc định app lưu dữ liệu vào file SQLite trên ổ đĩa của hosting. Gói miễn phí
(Render/Railway) **xóa ổ đĩa tạm mỗi lần deploy lại code** → mất hết dữ liệu
(tài khoản, sản phẩm, báo cáo). Cách khắc phục: dùng database online miễn phí
của Turso (SQLite trên cloud, app tương thích hoàn toàn, không cần đổi gì thêm).

Các bước (làm 1 lần, khoảng 5 phút):

1. Vào https://turso.tech → **Sign Up** (tài khoản miễn phí).
2. Cài công cụ Turso theo hướng dẫn trên trang rồi đăng nhập: `turso auth login`
3. Tạo database (region Singapore cho gần Việt Nam):
   `turso db create apyko-agency --region sin`
4. Lấy địa chỉ database: `turso db show apyko-agency --url`
   → dạng `libsql://apyko-agency-<ten-ban>.turso.io`
5. Tạo mã token: `turso db tokens create apyko-agency`
6. Trên Render (mục **Environment Variables** của service), thêm 2 biến:
   - `TURSO_DATABASE_URL` = địa chỉ ở bước 4
   - `TURSO_AUTH_TOKEN` = mã token ở bước 5
7. Render tự deploy lại → từ nay dữ liệu nằm trên Turso, deploy lại code bao
   nhiêu lần cũng không mất.

> Khi chưa đặt 2 biến này, app vẫn chạy SQLite local như cũ — không vỡ gì cả.
> Muốn quay lại SQLite local thì xóa 2 biến trên là xong.

## Biến môi trường đầy đủ

| Biến | Bắt buộc | Mặc định | Ghi chú |
|---|---|---|---|
| `SECRET_KEY` | Có (production) | rỗng | Chuỗi bí mật, không chia sẻ |
| `OWNER_USERNAME` / `OWNER_PASSWORD` | Không | rỗng | Bỏ trống thì dùng trang `/setup` |
| `DATABASE_PATH` | Không | `./data/apyko_agency.db` | File SQLite (bỏ qua khi dùng Turso) |
| `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` | Không | rỗng | Đủ cả 2 → dùng Turso remote; thiếu → SQLite local |
| `PORT` | Không | `8000` | Hosting tự đặt |
| `COOKIE_SECURE` | Nên `true` khi deploy | `false` | Cookie chỉ qua HTTPS |
| `SESSION_DAYS` | Không | `30` | Số ngày duy trì đăng nhập |
| `LESSONS_DIR` | Không | `./lessons` | Thư mục 58 bài học |
| `DISABLE_BACKGROUND` | Không | rỗng | Đặt `1` để tắt luồng nền Daily Checklist (dùng cho test) |

## Kiểm thử

```bash
python -m pytest -q        # 110 test: tính toán, auth, phân quyền, CRUD, bài học, checklist, dashboard CEO
ruff check app tests       # lint sạch
ruff format --check app tests
```
