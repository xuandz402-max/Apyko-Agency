/* Apyko Agency — ô nhập ngày DD/MM/YYYY + giờ HH:MM (24 giờ) kiểu Việt Nam.
 *
 * Vì sao cần file này: <input type="date"> hiển thị theo ngôn ngữ của
 * trình duyệt trên từng máy (máy để tiếng Anh -> MM/DD/YYYY), HTML/CSS
 * không ép được định dạng. Giải pháp: dùng ô text có class "date-vn" /
 * "time-vn", file này lo mặt nạ gõ + đổi định dạng hiển thị.
 *
 * Hợp đồng dữ liệu KHÔNG đổi: server luôn nhận ISO "YYYY-MM-DD" (ngày)
 * và "HH:MM" (giờ) như trước:
 * - Khi tải trang: value ISO của ô date-vn được hiển thị lại DD/MM/YYYY.
 * - Khi form submit (bắt ở phase capture): đổi ngược DD/MM/YYYY -> ISO
 *   ngay trong field rồi form mới gửi đi (kể cả form gửi bằng fetch —
 *   handler của trang chạy ở phase bubble, sau capture).
 * - Ngày gõ sai (32/13/2026, 29/02/2026, thiếu phần...) -> chặn submit,
 *   viền đỏ + alert tiếng Việt. Ô rỗng không bắt buộc -> để rỗng.
 */
(function () {
  "use strict";

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function isLeap(y) {
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  }

  function daysInMonth(y, m) {
    var days = [31, isLeap(y) ? 29 : 28, 31, 30, 31, 30,
                31, 31, 30, 31, 30, 31];
    return days[m - 1];
  }

  function isRealDate(y, m, d) {
    return m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);
  }

  /* "2026-10-20" -> "20/10/2026". Không phải ISO ngày thật -> trả nguyên. */
  function isoToVN(iso) {
    var s = String(iso == null ? "" : iso).trim();
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (!m) return iso;
    if (!isRealDate(+m[1], +m[2], +m[3])) return iso;
    return m[3] + "/" + m[2] + "/" + m[1];
  }

  /* "20/10/2026" (hoặc "2/3/2026") -> "2026-10-20".
   * Đã là ISO ngày thật -> giữ nguyên (hàm dùng lặp lại an toàn).
   * Sai định dạng / ngày không có thật -> null. Chuỗi rỗng -> "". */
  function vnToISO(vn) {
    var s = String(vn == null ? "" : vn).trim();
    if (!s) return "";
    var iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (iso) {
      return isRealDate(+iso[1], +iso[2], +iso[3]) ? s : null;
    }
    var m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(s);
    if (!m) return null;
    var d = +m[1], mo = +m[2], y = +m[3];
    if (!isRealDate(y, mo, d)) return null;
    return y + "-" + pad2(mo) + "-" + pad2(d);
  }

  function isValidTime(s) {
    var m = /^(\d{1,2}):(\d{2})$/.exec(String(s == null ? "" : s).trim());
    if (!m) return false;
    return +m[1] <= 23 && +m[2] <= 59;
  }

  /* "9:05" -> "09:05"; sai -> null; rỗng -> "". */
  function normTime(s) {
    var t = String(s == null ? "" : s).trim();
    if (!t) return "";
    if (!isValidTime(t)) return null;
    var m = /^(\d{1,2}):(\d{2})$/.exec(t);
    return pad2(+m[1]) + ":" + m[2];
  }

  /* ---------------- mặt nạ khi gõ ---------------- */

  function maskDate(input) {
    var raw = input.value;
    var full = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(raw.trim());
    if (full) {  // dán 1 ngày đầy đủ (có thể thiếu số 0) -> chuẩn hóa luôn
      input.value = pad2(+full[1]) + "/" + pad2(+full[2]) + "/" + full[3];
      return;
    }
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw.trim())) {  // dán ISO -> hiện VN
      input.value = isoToVN(raw.trim());
      return;
    }
    var digits = raw.replace(/\D/g, "").slice(0, 8);
    var out = digits;
    if (digits.length > 4) {
      out = digits.slice(0, 2) + "/" + digits.slice(2, 4) + "/" + digits.slice(4);
    } else if (digits.length > 2) {
      out = digits.slice(0, 2) + "/" + digits.slice(2);
    }
    input.value = out;
  }

  function maskTime(input) {
    var raw = input.value;
    var full = /^(\d{1,2}):(\d{2})$/.exec(raw.trim());
    if (full) {
      input.value = pad2(+full[1]) + ":" + full[2];
      return;
    }
    var digits = raw.replace(/\D/g, "").slice(0, 4);
    var out = digits;
    if (digits.length > 2) out = digits.slice(0, 2) + ":" + digits.slice(2);
    input.value = out;
  }

  /* ---------------- trạng thái lỗi ---------------- */

  function markInvalid(input) {
    input.setAttribute("aria-invalid", "true");
    input.classList.add("input-invalid");
  }

  function clearInvalid(input) {
    input.removeAttribute("aria-invalid");
    input.classList.remove("input-invalid");
  }

  function fieldLabel(input) {
    var lab = input.closest ? input.closest("label") : null;
    var text = "";
    if (lab) {
      text = (lab.textContent || "").replace(/\s+/g, " ").trim();
      // Bỏ phần giá trị đang gõ nếu label bọc cả input (textContent gồm cả)
      text = text.replace(/[\d/:]+$/, "").trim();
    }
    if (!text) text = input.name || input.id || "";
    return text ? "Ô \"" + text + "\"" : "Ô ngày/giờ";
  }

  /* Kiểm 1 ô ngày. convert=true thì đổi value sang ISO khi hợp lệ.
   * Trả về null nếu ổn, hoặc câu lỗi tiếng Việt. */
  function checkDateField(input, convert) {
    var raw = input.value.trim();
    if (!raw) {
      if (input.required) {
        markInvalid(input);
        return fieldLabel(input) + ": chưa nhập ngày (cần dạng DD/MM/YYYY).";
      }
      clearInvalid(input);
      return null;
    }
    var iso = vnToISO(raw);
    if (iso === null) {
      markInvalid(input);
      return fieldLabel(input) + ": ngày \"" + raw + "\" không đúng. " +
             "Hãy nhập dạng DD/MM/YYYY (ngày/tháng/năm) và là ngày có thật.";
    }
    clearInvalid(input);
    if (convert) input.value = iso;
    return null;
  }

  function checkTimeField(input, convert) {
    var raw = input.value.trim();
    if (!raw) {
      if (input.required) {
        markInvalid(input);
        return fieldLabel(input) + ": chưa nhập giờ (cần dạng HH:MM).";
      }
      clearInvalid(input);
      return null;
    }
    var t = normTime(raw);
    if (t === null) {
      markInvalid(input);
      return fieldLabel(input) + ": giờ \"" + raw + "\" không đúng. " +
             "Hãy nhập dạng HH:MM (24 giờ, VD 08:30).";
    }
    clearInvalid(input);
    if (convert) input.value = t;
    return null;
  }

  /* ---------------- API cho script riêng của trang ----------------
   * (VD form GMV/Báo cáo ngày tự gán ngày bằng JS: dùng toDisplay khi gán
   * để ô hiện DD/MM/YYYY; khi đọc để gửi, form-submit capture đã đổi ISO.) */
  var api = {
    toDisplay: isoToVN,
    toISO: vnToISO,
    isValidTime: isValidTime,
    normTime: normTime,
    isRealDate: isRealDate
  };
  if (typeof window !== "undefined") window.DateVN = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;  // cho phép test bằng node
  }

  if (typeof document === "undefined") return;

  /* ---------------- khởi tạo khi tải trang ---------------- */

  function init() {
    var dates = document.querySelectorAll("input.date-vn");
    for (var i = 0; i < dates.length; i++) {
      if (dates[i].value) dates[i].value = isoToVN(dates[i].value);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* Mặt nạ gõ (ủy quyền sự kiện — chạy cho mọi ô date-vn/time-vn). */
  document.addEventListener("input", function (ev) {
    var t = ev.target;
    if (!t.classList) return;
    if (t.classList.contains("date-vn")) {
      maskDate(t);
      if (t.classList.contains("input-invalid")) checkDateField(t, false);
    } else if (t.classList.contains("time-vn")) {
      maskTime(t);
      if (t.classList.contains("input-invalid")) checkTimeField(t, false);
    }
  });

  /* Rời ô: chuẩn hóa (thêm số 0) nếu đúng, đánh dấu đỏ nếu sai.
   * (Trang Mẫu checklist lưu bằng nút bấm + fetch, không qua form submit,
   * nên kiểm ngay tại đây để user thấy lỗi trước khi bấm Lưu.) */
  document.addEventListener("focusout", function (ev) {
    var t = ev.target;
    if (!t.classList) return;
    if (t.classList.contains("date-vn")) {
      var raw = t.value.trim();
      if (raw) {
        var iso = vnToISO(raw);
        if (iso) { t.value = isoToVN(iso); clearInvalid(t); }
        else markInvalid(t);
      } else {
        clearInvalid(t);
      }
    } else if (t.classList.contains("time-vn")) {
      var v = t.value.trim();
      if (v) {
        var nt = normTime(v);
        if (nt) { t.value = nt; clearInvalid(t); }
        else markInvalid(t);
      } else {
        clearInvalid(t);
      }
    }
  });

  /* Chặn submit ở phase capture: kiểm TẤT CẢ ô ngày/giờ trong form trước,
   * ô nào sai -> chặn + alert; tất cả đúng -> đổi sang ISO ngay trong
   * field rồi để form gửi đi như bình thường. */
  document.addEventListener("submit", function (ev) {
    var form = ev.target;
    if (!form.querySelectorAll) return;
    var dates = form.querySelectorAll("input.date-vn");
    var times = form.querySelectorAll("input.time-vn");
    if (!dates.length && !times.length) return;

    var errors = [];
    var i, err;
    for (i = 0; i < dates.length; i++) {
      err = checkDateField(dates[i], false);
      if (err) errors.push(err);
    }
    for (i = 0; i < times.length; i++) {
      err = checkTimeField(times[i], false);
      if (err) errors.push(err);
    }
    if (errors.length) {
      ev.preventDefault();
      ev.stopPropagation();
      alert(errors[0]);
      var bad = form.querySelector("input.input-invalid");
      if (bad) bad.focus();
      return;
    }
    // Tất cả hợp lệ -> đổi sang ISO ngay trong field rồi mới gửi.
    for (i = 0; i < dates.length; i++) {
      if (dates[i].value.trim()) dates[i].value = vnToISO(dates[i].value);
    }
    for (i = 0; i < times.length; i++) {
      if (times[i].value.trim()) times[i].value = normTime(times[i].value);
    }
  }, true);
})();
