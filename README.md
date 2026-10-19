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
> tạm — nếu deploy lại code, dữ liệu có thể mất. **Hãy xuất CSV sản phẩm định kỳ**
> (nút Xuất CSV ở trang Sản phẩm) để sao lưu. Muốn giữ dữ liệu vĩnh viễn: nâng
> cấp gói có Persistent Disk và gắn vào `/srv/data`.

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

## Biến môi trường đầy đủ

| Biến | Bắt buộc | Mặc định | Ghi chú |
|---|---|---|---|
| `SECRET_KEY` | Có (production) | rỗng | Chuỗi bí mật, không chia sẻ |
| `OWNER_USERNAME` / `OWNER_PASSWORD` | Không | rỗng | Bỏ trống thì dùng trang `/setup` |
| `DATABASE_PATH` | Không | `./data/apyko_agency.db` | File SQLite |
| `PORT` | Không | `8000` | Hosting tự đặt |
| `COOKIE_SECURE` | Nên `true` khi deploy | `false` | Cookie chỉ qua HTTPS |
| `SESSION_DAYS` | Không | `30` | Số ngày duy trì đăng nhập |
| `LESSONS_DIR` | Không | `./lessons` | Thư mục 58 bài học |

## Kiểm thử

```bash
python -m pytest -q        # 41 test: tính toán, auth, phân quyền, CRUD, bài học
ruff check app tests       # lint sạch
ruff format --check app tests
```
