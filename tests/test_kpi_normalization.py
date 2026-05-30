"""
KPI Normalization 單元測試 — Wave 2。

測試純函數：parse_number、parse_markdown_rows、extract_kpi_from_markdown。
不依賴 MongoDB 或 Claude。
"""
import pytest
from services.kpi_normalization import (
    parse_number,
    parse_markdown_rows,
    extract_kpi_from_markdown,
    detect_unit,
    _KPI_KEYWORDS,
)


# ── parse_number ──────────────────────────────────────────────────────────────

class TestParseNumber:
    def test_basic_integer(self):
        assert parse_number("1234567") == 1234567.0

    def test_comma_separated(self):
        assert parse_number("1,234,567") == 1234567.0

    def test_decimal(self):
        assert parse_number("12.5") == 12.5

    def test_percent_suffix(self):
        assert parse_number("37.5%") == 37.5

    def test_percent_fullwidth(self):
        assert parse_number("37.5％") == 37.5

    def test_bracket_negative_ascii(self):
        assert parse_number("(1,234)") == -1234.0

    def test_bracket_negative_fullwidth(self):
        assert parse_number("（1,234）") == -1234.0

    def test_bracket_negative_with_decimal(self):
        assert parse_number("(12.5)") == -12.5

    def test_empty_string(self):
        assert parse_number("") is None

    def test_dash(self):
        assert parse_number("-") is None

    def test_em_dash(self):
        assert parse_number("—") is None

    def test_na(self):
        assert parse_number("N/A") is None

    def test_double_dash(self):
        assert parse_number("--") is None

    def test_whitespace_only(self):
        assert parse_number("   ") is None

    def test_zero(self):
        assert parse_number("0") == 0.0

    def test_negative_sign(self):
        assert parse_number("-1,234") == -1234.0

    def test_chinese_unit_suffix_ignored(self):
        # 1,234千元 → 取 1234，不換算
        assert parse_number("1,234千元") == 1234.0

    def test_fullwidth_comma(self):
        assert parse_number("1，234，567") == 1234567.0

    def test_non_numeric(self):
        assert parse_number("無資料") is None


# ── parse_markdown_rows ───────────────────────────────────────────────────────

class TestParseMarkdownRows:
    def test_basic_table(self):
        md = (
            "| 項目 | 本期 | 上期 |\n"
            "| --- | --- | --- |\n"
            "| 營業收入 | 1,234,567 | 987,654 |\n"
        )
        rows = parse_markdown_rows(md)
        assert len(rows) == 2  # header + data, separator skipped
        assert rows[0] == ["項目", "本期", "上期"]
        assert rows[1] == ["營業收入", "1,234,567", "987,654"]

    def test_separator_skipped(self):
        md = "| a | b |\n| --- | --- |\n| x | y |\n"
        rows = parse_markdown_rows(md)
        assert all("---" not in r[0] for r in rows)

    def test_empty_string(self):
        assert parse_markdown_rows("") == []

    def test_no_pipe(self):
        assert parse_markdown_rows("plain text line") == []

    def test_cells_stripped(self):
        md = "|  a  |  b  |\n"
        rows = parse_markdown_rows(md)
        assert rows[0] == ["a", "b"]


# ── extract_kpi_from_markdown ─────────────────────────────────────────────────

class TestExtractKpiFromMarkdown:
    _TABLE = (
        "| 項目 | 2025Q4 | 2024Q4 |\n"
        "| --- | --- | --- |\n"
        "| 營業收入 | 1,234,567 | 987,654 |\n"
        "| 毛利率 | 37.5% | 35.0% |\n"
        "| 每股盈餘 | 3.20 | 2.80 |\n"
        "| 短期借款 | (50,000) | 60,000 |\n"
        "| 無相關欄位 | - | - |\n"
    )

    def test_revenue_found(self):
        value, raw = extract_kpi_from_markdown(self._TABLE, ["營業收入"])
        assert value == 1234567.0
        assert raw == "1,234,567"

    def test_gross_margin_found(self):
        value, raw = extract_kpi_from_markdown(self._TABLE, ["毛利率"])
        assert value == 37.5
        assert raw == "37.5%"

    def test_eps_found(self):
        value, raw = extract_kpi_from_markdown(self._TABLE, ["每股盈餘"])
        assert value == 3.20

    def test_bracket_negative_debt(self):
        value, raw = extract_kpi_from_markdown(self._TABLE, ["短期借款"])
        assert value == -50000.0

    def test_not_found_returns_none(self):
        value, raw = extract_kpi_from_markdown(self._TABLE, ["現金及約當現金"])
        assert value is None
        assert raw == ""

    def test_dash_value_skips_to_next_column(self):
        # label 欄命中，第二欄是 "-"，應跳過並嘗試下一欄
        md = (
            "| 項目 | 本期 | 前期 |\n"
            "| --- | --- | --- |\n"
            "| 營業收入 | - | 987,654 |\n"
        )
        value, raw = extract_kpi_from_markdown(md, ["營業收入"])
        assert value == 987654.0

    def test_empty_table(self):
        value, raw = extract_kpi_from_markdown("", ["營業收入"])
        assert value is None

    def test_english_keyword_match(self):
        md = (
            "| Item | Current | Prior |\n"
            "| --- | --- | --- |\n"
            "| Net Revenue | 1,000 | 900 |\n"
        )
        value, raw = extract_kpi_from_markdown(md, ["Net Revenue"])
        assert value == 1000.0


# ── detect_unit ───────────────────────────────────────────────────────────────

class TestDetectUnit:
    def test_detects_qianyuan(self):
        assert detect_unit("單位：千元") == "千元"

    def test_detects_baiwan(self):
        assert detect_unit("（單位：百萬元）") == "百萬元"

    def test_no_unit(self):
        assert detect_unit("一般表格沒有單位") is None


# ── KPI keyword registry completeness ────────────────────────────────────────

def test_all_8_kpis_defined():
    expected = {
        "revenue", "gross_margin", "operating_income", "net_income",
        "eps", "cash_and_equiv", "total_debt", "operating_cash_flow",
    }
    assert set(_KPI_KEYWORDS.keys()) == expected


def test_each_kpi_has_at_least_one_chinese_keyword():
    for kpi_id, keywords in _KPI_KEYWORDS.items():
        has_chinese = any(
            any("一" <= c <= "鿿" for c in kw)
            for kw in keywords
        )
        assert has_chinese, f"{kpi_id} 沒有中文關鍵字"
