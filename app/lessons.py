"""Nạp 58 bài học Apyko Uni từ thư mục lessons/ và render Markdown sang HTML.

Chỉ dùng stdlib. Hỗ trợ: tiêu đề #/##/###/####, **đậm**, *nghiêng*,
~~gạch ngang~~, `mã`, [liên kết](url), danh sách - / 1. (lồng nhau),
bảng | a | b |, trích dẫn >.
"""

import html
import os
import re

from . import config


def _load_lessons() -> list:
    lessons = []
    if not os.path.isdir(config.LESSONS_DIR):
        return lessons
    files = sorted(
        f for f in os.listdir(config.LESSONS_DIR) if f.endswith(".md") and re.match(r"^\d{2}-", f)
    )
    for fn in files:
        path = os.path.join(config.LESSONS_DIR, fn)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        lines = text.split("\n")
        title = fn
        body_lines = lines
        for i, line in enumerate(lines):
            m = re.match(r"^#\s+(.*)", line.strip())
            if m:
                title = m.group(1).strip()
                body_lines = lines[i + 1 :]
                break
        lesson_id = fn[:-3]  # bỏ .md
        lessons.append(
            {
                "id": lesson_id,
                "title": title,
                "body_md": "\n".join(body_lines).strip(),
                "filename": fn,
            }
        )
    return lessons


_LESSONS: list | None = None


def list_lessons() -> list:
    global _LESSONS
    if _LESSONS is None:
        _LESSONS = _load_lessons()
    return _LESSONS


def get_lesson(lesson_id: str) -> dict | None:
    for lesson in list_lessons():
        if lesson["id"] == lesson_id:
            return lesson
    return None


# ------------------------- mini markdown renderer -------------------------


def _inline(text: str) -> str:
    text = html.escape(text)
    # `mã`
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # ![chú thích](src) — ảnh minh họa trong bài học (src nội bộ /static/ hoặc http)
    text = re.sub(
        r"!\[([^\]]*)\]\((/static/[^)\s]+|https?[^)\s]+)\)",
        r'<img src="\2" alt="\1" class="lesson-img" loading="lazy">',
        text,
    )
    # [chữ](url)
    text = re.sub(
        r"\[([^\]]+)\]\((https?[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    # **đậm**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # ~~gạch~~
    text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", text)
    # *nghiêng*
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    return text


def _is_table_sep(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def render_markdown(md: str) -> str:
    """Markdown → HTML (đủ cho nội dung bài học)."""
    lines = md.split("\n")
    out: list[str] = []
    i = 0
    list_stack: list[str] = []  # 'ul' hoặc 'ol' theo độ sâu

    def close_lists(to_depth: int = 0):
        while len(list_stack) > to_depth:
            out.append(f"</{list_stack.pop()}>")

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            # Danh sách "lỏng" (các mục cách nhau bởi dòng trống) vẫn là MỘT
            # danh sách: không đóng list nếu dòng có chữ tiếp theo là một mục
            # list — nếu không, danh sách đánh số sẽ toàn hiện "1."
            if list_stack:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and re.match(
                    r"^(\s*)([-*]|\d+[.)])\s+", lines[j]
                ):
                    i += 1
                    continue
            close_lists()
            i += 1
            continue

        # Bảng: khối các dòng bắt đầu bằng "|" (có hoặc không có dòng phân cách).
        # Dòng phân cách (nếu còn) bị bỏ qua, không in ra — trước đây thiếu nó
        # là bảng vỡ thành chữ thô lộ dấu "|".
        if stripped.startswith("|") and "|" in stripped[1:]:
            close_lists()
            block = []
            j = i
            while j < len(lines):
                s = lines[j].strip()
                if s.startswith("|"):
                    if not _is_table_sep(lines[j]):
                        block.append(s)
                    j += 1
                    continue
                if not s:
                    # Cho phép dòng trống chen giữa các dòng bảng (định dạng
                    # xuất từ Google Docs) — chỉ tiếp tục nếu dòng có chữ
                    # tiếp theo vẫn là dòng bảng.
                    k = j + 1
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k < len(lines) and lines[k].strip().startswith("|"):
                        j += 1
                        continue
                break
            if len(block) >= 2:
                rows = [
                    [c.strip() for c in r.strip("|").split("|")] for r in block
                ]
                ncols = max(len(r) for r in rows)
                first = rows[0]
                has_header = len(first) == ncols and all(
                    c and not any(ch.isdigit() for ch in c) and len(c) <= 40
                    for c in first
                )
                out.append('<div class="md-table-wrap"><table class="md-table">')
                start = 0
                if has_header:
                    out.append(
                        "<thead><tr>"
                        + "".join(f"<th>{_inline(h)}</th>" for h in first)
                        + "</tr></thead>"
                    )
                    start = 1
                out.append("<tbody>")
                for r in rows[start:]:
                    cells = (r + [""] * ncols)[:ncols]
                    out.append(
                        "<tr>"
                        + "".join(f"<td>{_inline(c)}</td>" for c in cells)
                        + "</tr>"
                    )
                out.append("</tbody></table></div>")
                i = j
                continue
            # Chỉ 1 dòng ống đơn độc: rơi xuống xử lý đoạn văn như cũ

        # Tiêu đề
        m = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if m:
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Trích dẫn
        if stripped.startswith(">"):
            close_lists()
            quotes = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quotes.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" + "<br>".join(_inline(q) for q in quotes) + "</blockquote>")
            continue

        # Đường kẻ ngang
        if re.fullmatch(r"(-{3,}|\*{3,})", stripped):
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # Danh sách
        m = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)", line)
        if m:
            indent = len(m.group(1).replace("\t", "    "))
            depth = indent // 2
            kind = "ol" if re.match(r"\d+[.)]", m.group(2)) else "ul"
            while len(list_stack) > depth + 1:
                out.append(f"</{list_stack.pop()}>")
            while len(list_stack) < depth + 1:
                list_stack.append(kind)
                out.append(f"<{kind}>")
            if list_stack and list_stack[-1] != kind:
                out.append(f"</{list_stack.pop()}>")
                list_stack.append(kind)
                out.append(f"<{kind}>")
            out.append(f"<li>{_inline(m.group(3))}</li>")
            i += 1
            continue

        # Đoạn văn: gom các dòng liên tiếp
        close_lists()
        para = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt:
                break
            if re.match(r"^(#{1,4}\s|>\s|[-*]\s|\d+[.)]\s|(-{3,}|\*{3,}))", nxt):
                break
            if "|" in nxt and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
                break
            para.append(nxt)
            i += 1
        out.append(f"<p>{'<br>'.join(_inline(p) for p in para)}</p>")

    close_lists()
    return "\n".join(out)
