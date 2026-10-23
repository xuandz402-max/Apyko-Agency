# Kỹ thuật Set Voucher tăng AOV

## 2 Kỹ thuật Set Voucher tăng AOV + Xây bậc thang khuyến mãi

Từ tư duy "voucher = đòn bẩy AOV" ở bài trước, dưới đây là 2 kỹ thuật cụ thể để áp dụng, và cách xây cả hệ thống bậc thang khuyến mãi cho 1 gian hàng.

## Kỹ thuật 1: Voucher toàn shop theo ngưỡng đơn hàng (mồi nhử AOV)

Cách làm

- Xác định giá sản phẩm chủ lực khách hay mua lẻ 1 món.

- Đặt mức tối thiểu của voucher CAO HƠN giá sản phẩm đó — và quan trọng nhất: mức chênh lệch KHÔNG được trùng với giá bất kỳ sản phẩm rẻ nào có sẵn trong shop.

- Khách buộc phải thêm 1 sản phẩm khác (thường giá tối thiểu vài trăm nghìn) mới đạt ngưỡng.

Vì sao hiệu quả

Nếu shop có sẵn sản phẩm giá đúng bằng phần chênh lệch (VD chênh 10k mà shop có món 10k), khách sẽ mua đúng món đó cho đủ ngưỡng rồi dừng — AOV không tăng được bao nhiêu. Ngưỡng phải đặt sao cho khách BUỘC phải cân nhắc mua thêm 1 sản phẩm có giá trị thật.

## Kỹ thuật 2: Mã giảm giá cố định theo 1 sản phẩm cụ thể (ngưỡng 0đ)

Thay vì áp cho toàn shop kèm điều kiện, tạo 1 mã giảm giá cố định số tiền, ngưỡng đơn tối thiểu 0đ, chỉ áp dụng cho 1 sản phẩm nhất định. Ví dụ sản phẩm giá 500k, tạo mã giảm 50k cho đơn từ 0đ với riêng sản phẩm đó.

- Mã dạng này thu hút khách hơn hẳn voucher toàn shop có điều kiện, vì khách thấy được lợi ích ngay lập tức, không cần tính toán "mua đủ ngưỡng".

- Lưu ý vận hành quan trọng: luôn bật cho phép khách lưu mã trước thời gian sử dụng (thu thập mã sớm) — khách lưu sẵn mã sẽ có xu hướng quay lại dùng đúng lúc mã kích hoạt, tăng tỷ lệ chuyển đổi khi tới đợt sale.

## Xây bậc thang khuyến mãi (nhiều mức trong cùng 1 shop)

Một gian hàng hoàn toàn có thể setup nhiều mã giảm giá theo nhiều mức (level) cùng lúc, áp dụng đúng nguyên tắc "chi càng nhiều, ưu đãi càng tốt" để tạo cảm giác mua hời thật sự ở mọi phân khúc khách hàng:

| Mức | Ngưỡng đơn hàng | Mức giảm | Mục tiêu |
| 1 | Ngang giá 1 sản phẩm phổ biến | Giảm nhỏ | Chuyển đổi khách mới, chưa cần đẩy AOV mạnh |
| 2 | Cao hơn giá 1 sản phẩm chủ lực | Giảm vừa | Ép mua thêm 1 sản phẩm phụ — đúng nguyên tắc mồi nhử AOV |
| 3 | Cao hơn hẳn, tương đương 2-3 sản phẩm | Giảm sâu nhất | Khách chi tiêu lớn cảm thấy xứng đáng, tối đa AOV |

Điểm mấu chốt xuyên suốt cả bài: đặt mã giảm giá hay bất kỳ CTKM nào từ nay về sau, mục tiêu tối thượng luôn là tăng giá trị đơn hàng trung bình — nói đơn giản là để khách chi nhiều tiền hơn mỗi lần mua, đổi lại họ được mức ưu đãi tốt hơn và cảm thấy đó là 1 món hời thật sự.

### Lưu ý khi triển khai (tránh sai lầm thường gặp)

- Luôn đối chiếu lại giá toàn bộ sản phẩm trong shop trước khi chọn ngưỡng — tránh đặt ngưỡng trùng khớp với giá 1 sản phẩm bất kỳ, vì sẽ mất tác dụng "ép mua thêm".

- Tính lại biên lợi nhuận trước khi quyết định mức giảm — giảm sâu để đẩy AOV nhưng vẫn phải đảm bảo không lỗ trên tổng đơn.

- Theo dõi AOV thực tế sau khi áp dụng voucher để tinh chỉnh lại ngưỡng cho từng đợt sau, không đặt 1 lần rồi giữ nguyên mãi.
