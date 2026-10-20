"""Sinh app/data/pricing_categories.json từ sheet "Ngành hàng" của file Excel.

Nguồn sự thật: file "Dự tính giá bán" của user —
~/workspace/goals/thi-t-k-muse-ai-mvp-30-ng-y-cho-shop-s-ch-nh/hidden_files/pricing/du-tinh-gia-ban.xlsx

Chạy bằng system python3 (cần openpyxl):
    python3 hidden_files/gen_pricing_categories.py [đường-dẫn-xlsx]

Cột sheet: A = mã ngành, B = loại shop, D = ngành lớn, E = ngành nhỏ,
F = % phí ngành (thập phân, VD 0.02 = 2%). Giữ nguyên văn mã ngành.
"""

import json
import os
import sys

DEFAULT_XLSX = (
    "/home/hatch/workspace/goals/thi-t-k-muse-ai-mvp-30-ng-y-cho-shop-s-ch-nh"
    "/hidden_files/pricing/du-tinh-gia-ban.xlsx"
)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(_PROJECT_DIR, "app", "data", "pricing_categories.json")


def main() -> None:
    import openpyxl

    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    wb = openpyxl.load_workbook(xlsx, data_only=True, read_only=True)
    ws = wb["Ngành hàng"]
    rows = ws.iter_rows(min_row=2, values_only=True)
    cats = []
    seen = set()
    for code, shop_type, _group, big, small, fee in rows:
        if not code:
            continue
        code = str(code).strip()
        if code in seen:
            raise SystemExit(f"Mã ngành trùng trong file nguồn: {code}")
        seen.add(code)
        cats.append(
            {
                "code": code,
                "shop_type": (shop_type or "").strip(),
                "big": (big or "").strip(),
                "small": (small or "").strip(),
                "fee_rate": float(fee) if fee is not None else 0.0,
            }
        )
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(cats, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Đã ghi {len(cats)} ngành hàng -> {OUT_PATH}")


if __name__ == "__main__":
    main()
