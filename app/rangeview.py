"""Chọn khoảng ngày kiểu Shopee Ads — DÙNG CHUNG cho mọi trang số liệu.

Một bộ chọn duy nhất cho Dashboard CEO / GMV Max / KPI / Báo cáo ngày:

- Tham số: ?from=YYYY-MM-DD&to=YYYY-MM-DD (ngày ISO).
- Preset nhanh lăn theo HÔM NAY (kiểu Shopee Ads): "Hôm nay" (hôm nay),
  "Hôm qua", "7 ngày qua" (hôm nay - 6 -> hôm nay), "30 ngày qua",
  "90 ngày qua". Ngoài preset ra là khoảng Tự chọn do user bấm trên lịch.
- Khoảng so sánh = khoảng DÀI BẰNG khoảng xem nằm LIỀN TRƯỚC nó.
- Không có param -> preset mặc định của trang (LAST_7 cho CEO/GMV/KPI,
  LAST_30 cho Báo cáo ngày). Param sai định dạng / to < from / khoảng
  dài hơn 366 ngày -> quay về preset mặc định, không bao giờ văng lỗi.

resolve_range trả dict có cùng "họ khóa" với periods.resolve_period
(cur_start/cur_end/prev_start/prev_end/from/to/num_days/label_cur/
label_prev/cur_name/prev_name) để các thẻ chỉ số dùng lại được ngay,
kèm thêm: days, preset (khóa preset hoặc "custom"), preset_label,
presets (danh sách preset kèm khoảng tuyệt đối + cờ active để vẽ thanh
chọn), today (ngày neo — JS lịch lấy làm mốc "hôm nay") và capped=False
(giữ tương thích mẫu trang KPI; bộ chọn này tự chặn 366 ngày).
"""

from datetime import date, timedelta

from .periods import _parse_iso

MAX_DAYS = 366

# key -> (nhãn, số ngày lùi của ngày bắt đầu, số ngày lùi của ngày kết
# thúc) tính từ hôm nay. "1 tuần qua / 1 tháng qua / 3 tháng qua" của
# Shopee Ads tương ứng 7 / 30 / 90 ngày qua ở đây.
PRESETS = (
    ("today", "Hôm nay", 0, 0),
    ("yesterday", "Hôm qua", 1, 1),
    ("last7", "7 ngày qua", 6, 0),
    ("last30", "30 ngày qua", 29, 0),
    ("last90", "90 ngày qua", 89, 0),
)
PRESET_LABELS = {key: label for key, label, _bf, _bt in PRESETS}


def preset_range(key: str, today: str) -> tuple[str, str]:
    """Khoảng (from, to) tuyệt đối của 1 preset tính theo ngày neo."""
    t = date.fromisoformat(today)
    for k, _label, back_from, back_to in PRESETS:
        if k == key:
            return (
                (t - timedelta(days=back_from)).isoformat(),
                (t - timedelta(days=back_to)).isoformat(),
            )
    raise KeyError(key)


def _fmt_dmy(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"


def range_label(start: str, end: str) -> str:
    """Nhãn khoảng kiểu Shopee: "DD/MM - DD/MM/YYYY" (1 ngày -> "DD/MM/YYYY")."""
    if start == end:
        return _fmt_dmy(start)
    return f"{start[8:10]}/{start[5:7]} - {_fmt_dmy(end)}"


def resolve_range(params, today: str, default: str = "last7") -> dict:
    """Giải quyết ?from&to thành khoảng xem + khoảng so sánh liền trước.

    `params`: mapping có khóa "from", "to" (giá trị có thể None).
    `today`: ngày neo 'YYYY-MM-DD' (preset tính quanh ngày này).
    `default`: preset dùng khi param thiếu/sai ("last7" hoặc "last30").
    """
    if default not in PRESET_LABELS:
        default = "last7"
    cur = None
    if params:
        d_from = _parse_iso(params.get("from"))
        d_to = _parse_iso(params.get("to"))
        if (
            d_from is not None
            and d_to is not None
            and d_to >= d_from
            and (d_to - d_from).days + 1 <= MAX_DAYS
        ):
            cur = (d_from.isoformat(), d_to.isoformat())
    if cur is None:
        cur = preset_range(default, today)

    preset = "custom"
    for key, _label, _bf, _bt in PRESETS:
        if preset_range(key, today) == cur:
            preset = key
            break

    days = (date.fromisoformat(cur[1]) - date.fromisoformat(cur[0])).days + 1
    prev_end_d = date.fromisoformat(cur[0]) - timedelta(days=1)
    prev_start_d = prev_end_d - timedelta(days=days - 1)
    prev = (prev_start_d.isoformat(), prev_end_d.isoformat())
    presets = []
    for key, label, _bf, _bt in PRESETS:
        p_from, p_to = preset_range(key, today)
        presets.append(
            {
                "key": key,
                "label": label,
                "from": p_from,
                "to": p_to,
                "active": key == preset,
            }
        )
    return {
        "cur_start": cur[0],
        "cur_end": cur[1],
        "prev_start": prev[0],
        "prev_end": prev[1],
        "from": cur[0],
        "to": cur[1],
        "days": days,
        "num_days": days,
        "preset": preset,
        "preset_label": PRESET_LABELS.get(preset),
        "cur_name": PRESET_LABELS.get(preset, "Kỳ đã chọn"),
        "prev_name": "khoảng liền trước",
        "label_cur": range_label(*cur),
        "label_prev": range_label(*prev),
        "presets": presets,
        "today": today,
        "capped": False,
    }
