"""Chọn khoảng thời gian + so sánh kỳ — dùng chung cho các trang dữ liệu.

Một "kỳ" gồm khoảng hiện tại và khoảng LIỀN TRƯỚC DÀI BẰNG NHAU để so sánh
công bằng:
- day:    hôm nay vs hôm qua.
- week:   thứ Hai tuần này -> hôm nay vs cùng số ngày đầu tuần trước.
- month:  ngày 1 tháng này -> hôm nay vs cùng số ngày đầu tháng trước
          (tháng trước ngắn hơn thì dừng ở ngày cuối của tháng trước).
- custom: khoảng [from, to] người dùng tự chọn; kỳ trước là khoảng dài
          bằng nó nằm ngay trước from.

Công thức day/week/month lấy nguyên từ ceo.period_ranges (Dashboard CEO)
để mọi trang không lệch nhau. Kỳ không hợp lệ / custom sai định dạng hoặc
to < from -> quay về day (không bao giờ văng lỗi vì query param).

delta_pct(): kỳ trước = 0 hoặc thiếu 1 trong 2 phía -> None (giao diện
hiện "—", không bịa %). Giao diện dùng class .delta-up (xanh lá #15803D,
▲) / .delta-down (đỏ #DC2626, ▼) như Dashboard CEO.
"""

import re
from datetime import date, timedelta

from . import ceo

PERIODS = ("day", "week", "month", "custom")

_PERIOD_NAMES = {
    "day": ("Hôm nay", "hôm qua"),
    "week": ("Tuần này", "tuần trước"),
    "month": ("Tháng này", "tháng trước"),
    "custom": ("Kỳ đã chọn", "kỳ trước"),
}

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso(value) -> date | None:
    """Chuỗi 'YYYY-MM-DD' chặt chẽ -> date; sai -> None."""
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _fmt_dm(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _range_label(start: str, end: str) -> str:
    # Nhãn khoảng ngày kiểu DD/MM - DD/MM (dùng en-dash, khớp Dashboard CEO).
    return _fmt_dm(start) if start == end else f"{_fmt_dm(start)} – {_fmt_dm(end)}"  # noqa: RUF001


def _num_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1


def resolve_period(params, today: str) -> dict:
    """Giải quyết query param thành khoảng kỳ hiện tại + kỳ trước.

    `params`: mapping có khóa "period", "from", "to" (giá trị có thể None).
    `today`: ngày neo 'YYYY-MM-DD' (day/week/month tính quanh ngày này;
    custom thì from/to là tuyệt đối, today chỉ dùng khi phải quay về day).

    Trả dict: period, cur_start, cur_end, prev_start, prev_end, label_cur,
    label_prev, cur_name, prev_name, from, to (from/to = khoảng hiện tại,
    để điền sẵn 2 ô date của form Tự chọn), num_days.
    """
    raw = params.get("period") if params else None
    period = raw if raw in PERIODS else "day"
    custom_start = custom_end = None
    if period == "custom":
        custom_start = _parse_iso(params.get("from"))
        custom_end = _parse_iso(params.get("to"))
        if custom_start is None or custom_end is None or custom_end < custom_start:
            period = "day"
    if period == "custom":
        length = (custom_end - custom_start).days + 1
        prev_end = custom_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=length - 1)
        cur = (custom_start.isoformat(), custom_end.isoformat())
        prev = (prev_start.isoformat(), prev_end.isoformat())
    else:
        cur, prev = ceo.period_ranges(today, period)
    cur_name, prev_name = _PERIOD_NAMES[period]
    return {
        "period": period,
        "cur_start": cur[0],
        "cur_end": cur[1],
        "prev_start": prev[0],
        "prev_end": prev[1],
        "label_cur": _range_label(*cur),
        "label_prev": _range_label(*prev),
        "cur_name": cur_name,
        "prev_name": prev_name,
        "from": cur[0],
        "to": cur[1],
        "num_days": _num_days(*cur),
    }


def delta_pct(cur, prev) -> float | None:
    """% thay đổi của kỳ này so với kỳ trước, làm tròn 0.1.

    Thiếu 1 trong 2 phía hoặc kỳ trước = 0 -> None (không bịa %).
    """
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / prev * 100, 1)


def cap_period(info: dict, max_days: int = 31) -> dict:
    """Chặn kỳ hiện tại tối đa `max_days` ngày (giữ các ngày GẦN NHẤT).

    Dùng cho trang phải cộng dồn từng ngày (Bảng Leader checklist): kỳ quá
    dài làm chậm trang. Kỳ trước được tính lại liền kề với độ dài bằng kỳ
    đã chặn. Trả về bản sao của `info` kèm cờ "capped" (True/False).
    """
    out = dict(info)
    out["capped"] = False
    if info["num_days"] <= max_days:
        return out
    end = date.fromisoformat(info["cur_end"])
    start = end - timedelta(days=max_days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=max_days - 1)
    cur = (start.isoformat(), end.isoformat())
    prev = (prev_start.isoformat(), prev_end.isoformat())
    out.update(
        cur_start=cur[0],
        cur_end=cur[1],
        prev_start=prev[0],
        prev_end=prev[1],
        label_cur=_range_label(*cur),
        label_prev=_range_label(*prev),
        num_days=max_days,
        capped=True,
    )
    out["from"], out["to"] = cur
    return out
