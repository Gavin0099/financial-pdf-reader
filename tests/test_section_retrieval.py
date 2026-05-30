"""
Section-aware retrieval 單元測試 — 3B。

測試純函數 _allocate_section_budget，不依賴 MongoDB 或 Claude。
四個驗收標準：
  1. 每個 section 分配量不超過其 SECTION_QUOTA 上限
  2. 總分配量不超過 budget
  3. 當 sum(desired) > budget 時，總分配量 == budget（配額被完整利用）
  4. section=unknown 的兜底邏輯有效（unknown 有配額）
"""
from types import SimpleNamespace

from services.summarization import _allocate_section_budget, _SECTION_QUOTA


# ── 輔助工具 ──────────────────────────────────────────────────────────────────

def _chunks(n: int) -> list:
    """回傳 n 個假 chunk，內容不重要（allocation 只看數量）。"""
    return [SimpleNamespace(page=i + 1, text="x") for i in range(n)]


# ── 基本約束 ──────────────────────────────────────────────────────────────────

def test_total_does_not_exceed_budget():
    """任何情況下 sum(allocation) <= budget。"""
    by_section = {s: _chunks(20) for s in list(_SECTION_QUOTA.keys())[:10]}
    allocation = _allocate_section_budget(by_section, budget=60)
    assert sum(allocation.values()) <= 60


def test_each_section_does_not_exceed_its_quota():
    """每個 section 的分配量不超過 SECTION_QUOTA 中的上限。"""
    by_section = {s: _chunks(50) for s in _SECTION_QUOTA}
    allocation = _allocate_section_budget(by_section, budget=60)
    for section, count in allocation.items():
        quota = _SECTION_QUOTA.get(section, _SECTION_QUOTA["unknown"])
        assert count <= quota, f"section '{section}': {count} > quota {quota}"


def test_budget_fully_utilised_when_supply_exceeds_budget():
    """
    當文件 chunks 充足（各 section 都有足夠 chunks）時，
    sum(allocation) 應等於 budget（不浪費名額）。
    """
    # 每個 section 各給 50 個 chunks，遠超任何配額
    by_section = {s: _chunks(50) for s in _SECTION_QUOTA}
    allocation = _allocate_section_budget(by_section, budget=60)
    assert sum(allocation.values()) == 60


def test_within_budget_no_scaling():
    """
    當 sum(desired) <= budget 時，不進行縮減，各 section 取滿 desired。
    """
    # 只有 3 個 section，各 5 個 chunks → total desired = 15 < 60
    by_section = {"營收": _chunks(5), "EPS": _chunks(5), "風險因素": _chunks(5)}
    allocation = _allocate_section_budget(by_section, budget=60)
    assert allocation["營收"] == 5
    assert allocation["EPS"] == 5
    assert allocation["風險因素"] == 5
    assert sum(allocation.values()) == 15


def test_unknown_section_gets_allocation():
    """
    unknown section 必須有配額（不被丟棄）。
    當文件中有 unknown chunks 時，allocation 中 unknown > 0。
    """
    by_section = {"unknown": _chunks(20)}
    allocation = _allocate_section_budget(by_section, budget=60)
    assert allocation.get("unknown", 0) > 0


def test_section_capped_by_actual_chunk_count():
    """
    即使 quota 是 12，但只有 3 個 chunks，分配量不超過 3。
    """
    by_section = {"營收": _chunks(3)}
    allocation = _allocate_section_budget(by_section, budget=60)
    assert allocation["營收"] == 3


def test_proportional_reduction_when_over_budget():
    """
    各 section 的 desired 比例在縮減後應大致維持。
    大 section（高 desired）縮減後仍多於小 section。
    """
    by_section = {
        "營收":      _chunks(20),  # desired = min(20, 12) = 12
        "董事會說明": _chunks(20),  # desired = min(20, 3)  = 3
    }
    # budget=10 < sum(desired)=15 → 需縮減
    allocation = _allocate_section_budget(by_section, budget=10)
    assert sum(allocation.values()) == 10
    # 大段落應獲得比小段落更多的 chunks
    assert allocation["營收"] > allocation["董事會說明"]


def test_empty_document_returns_empty():
    """空文件回傳全零分配。"""
    allocation = _allocate_section_budget({}, budget=60)
    assert allocation == {}


def test_unknown_quota_applied_to_unrecognised_section():
    """
    不在 _SECTION_QUOTA 中的 section 使用 unknown 的 quota 作為預設。
    """
    by_section = {"完全未知段落XYZ": _chunks(30)}
    allocation = _allocate_section_budget(by_section, budget=60)
    expected_max = _SECTION_QUOTA["unknown"]
    assert allocation.get("完全未知段落XYZ", 0) <= expected_max


def test_section_quota_covers_all_classifier_sections():
    """
    _SECTION_QUOTA 必須覆蓋 classify_chunk 可能輸出的所有 20 個段落名稱，
    確保沒有段落被靜默遺漏。
    """
    from services.classification import SECTIONS
    for s in SECTIONS:
        assert s in _SECTION_QUOTA, (
            f"section '{s}' 出現在 SECTIONS 但不在 _SECTION_QUOTA 中"
        )
