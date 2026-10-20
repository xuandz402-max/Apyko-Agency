/* Kiểm hàm thuần của static/date-vn.js bằng node.
 * Chạy: node tests/date_vn_node_test.js  (pytest cũng gọi file này nếu có node) */
"use strict";
const assert = require("assert");
const path = require("path");
const DateVN = require(path.join(__dirname, "..", "static", "date-vn.js"));

// ISO -> hiển thị VN
assert.strictEqual(DateVN.toDisplay("2026-10-20"), "20/10/2026");
assert.strictEqual(DateVN.toDisplay("2024-02-29"), "29/02/2024");
assert.strictEqual(DateVN.toDisplay(""), "");
assert.strictEqual(DateVN.toDisplay("20/10/2026"), "20/10/2026"); // không phải ISO -> giữ nguyên
assert.strictEqual(DateVN.toDisplay("2026-02-29"), "2026-02-29"); // ISO nhưng ngày không thật -> giữ nguyên

// VN -> ISO
assert.strictEqual(DateVN.toISO("20/10/2026"), "2026-10-20");
assert.strictEqual(DateVN.toISO("2026-10-20"), "2026-10-20"); // idempotent
assert.strictEqual(DateVN.toISO("2/3/2026"), "2026-03-02");   // không số 0 đầu
assert.strictEqual(DateVN.toISO(""), "");
assert.strictEqual(DateVN.toISO("29/02/2024"), "2024-02-29"); // năm nhuận: hợp lệ
assert.strictEqual(DateVN.toISO("29/02/2026"), null);         // 2026 không nhuận
assert.strictEqual(DateVN.toISO("31/04/2026"), null);         // tháng 4 có 30 ngày
assert.strictEqual(DateVN.toISO("32/13/2026"), null);
assert.strictEqual(DateVN.toISO("20/10/26"), null);           // năm phải 4 số
assert.strictEqual(DateVN.toISO("abc"), null);

// Giờ HH:MM 24h
assert.strictEqual(DateVN.normTime("9:05"), "09:05");
assert.strictEqual(DateVN.normTime("23:59"), "23:59");
assert.strictEqual(DateVN.normTime("00:00"), "00:00");
assert.strictEqual(DateVN.normTime(""), "");
assert.strictEqual(DateVN.normTime("24:00"), null);
assert.strictEqual(DateVN.normTime("12:60"), null);
assert.strictEqual(DateVN.isValidTime("08:30"), true);
assert.strictEqual(DateVN.isValidTime("8:30"), true);
assert.strictEqual(DateVN.isValidTime("25:00"), false);

console.log("date-vn node tests: ALL PASS");
