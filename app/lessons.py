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
            close_lists()
            i += 1
            continue

        # Bảng: dòng header + dòng phân cách
        if "|" in stripped and i + 1 < len(lines) and _is_table_sep(lines[i + 1]):
            close_lists()
            headers = [c.strip() for c in stripped.strip("|").split("|")]
            out.append('<div class="md-table-wrap"><table class="md-table"><thead><tr>')
            out.append("".join(f"<th>{_inline(h)}</th>" for h in headers))
            out.append("</tr></thead><tbody>")
            i += 2
            while i < len(lines) and "|" in lines[i].strip():
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                cells += [""] * (len(headers) - len(cells))
                out.append(
                    "<tr>"
                    + "".join(f"<td>{_inline(c)}</td>" for c in cells[: len(headers)])
                    + "</tr>"
                )
                i += 1
            out.append("</tbody></table></div>")
            continue

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
