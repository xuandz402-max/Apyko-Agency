# Tự cập nhật khi app đang chạy (bản máy tính Windows)

App đang chạy tự kiểm tra bản mới mỗi 10 phút (luồng nền trong
`app/selfupdate.py`, chỉ chạy trên Windows bản máy tính — không chạy trên
Render). Khi có bản mới, app tự tải về, ghi đè và khởi động lại; người dùng
chỉ cần tải lại trang (Ctrl+F5) là thấy bản mới.

## Quy tắc bắt buộc mỗi lần push

**Mỗi lần push phải tăng số trong `app/version.txt` lên 1 trước khi push,
nếu không app đang chạy sẽ không tự cập nhật.**

File `app/version.txt` chỉ chứa đúng một số nguyên (ví dụ `1`), không thêm
chữ hay ghi chú gì vào file đó.

## Cách nó so sánh bản

- App đọc số local từ `app/version.txt` của bản đang chạy.
- App tải file cùng tên trên nhánh main:
  `https://raw.githubusercontent.com/xuandz402-max/Apyko-Agency/main/app/version.txt`
- Số remote lớn hơn số local thì có bản mới. Mọi lỗi mạng, timeout, nội dung
  không phải số nguyên đều được bỏ qua lặng lẽ, app cũ vẫn chạy bình thường.

## Khi cập nhật, những gì được ghi đè (và không được ghi đè)

- ĐƯỢC ghi đè: `app/`, `templates/`, `static/`, `lessons/`.
- KHÔNG BAO GIỜ bị đụng tới: `data/` (dữ liệu + sao lưu + file đơn gốc),
  `python/`, `wheels/`, `.env.local`, mọi file `.bat` / launcher.
- Zip tải về hỏng hoặc giải nén lỗi thì hủy cập nhật, giữ nguyên bản cũ.

## Khởi động lại trên Windows

Sau khi ghi đè xong, app tạo một file `.bat` phụ trợ trong thư mục tạm rồi
thoát; file này chờ 3 giây, kill tiến trình còn giữ cổng 8000 rồi chạy lại
app bằng uvicorn (đúng cách launcher vẫn làm). Việc khởi động lại không phụ
thuộc vào việc trình duyệt có đang mở hay không.

## Chống cache trình duyệt

Mọi trang gắn `?v=<số bản>` vào link CSS và JS chính, nên sau khi cập nhật
trình duyệt tự tải CSS/JS mới (Ctrl+F5 chỉ là thói quen, không còn bắt buộc).

## Lưu ý kiểm chứng

- Bước khởi động lại trên Windows thật chưa kiểm chứng được trên máy Linux
  (chỉ kiểm chứng logic tạo lệnh bằng unit test) — lần chạy đầu tiên trên
  máy Windows của người dùng là kiểm chứng thật.
- Muốn tắt hẳn tự cập nhật: đặt biến môi trường `DISABLE_BACKGROUND=1`
  (cùng công tắc với scheduler nền) hoặc chạy trên Render (tự tắt).
