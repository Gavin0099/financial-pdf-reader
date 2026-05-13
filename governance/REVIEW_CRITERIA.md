---
audience: human-only
authority: reference
can_override: false
overridden_by: ~
default_load: never
---

# REVIEW_CRITERIA.md
**Code Review 與 Audit Protocol - v1.2**

> **Version**: 1.2 | **Priority**: 3（稽核協定）
>
> 定義如何 audit、批判、驗證 code change。
> 當 `SCOPE = review` 時載入。

---

## 0. Activation

當 `SCOPE = review` 時，這份文件生效。

啟用後：
- agent 應保持 governance-first
- 行為模式應轉成 skeptical verifier，而不是 implementer
- findings 必須綁定 evidence，而不是靠直覺

---

## 1. Review Philosophy

review 的目標是：
- 驗證變更是否可預期
- 驗證變更是否安全
- 驗證變更是否能在 governance 下被 review

不要因為變更很小，就假設它沒問題。
也不要在沒有指明 evidence 的情況下給 approval。

---

## 2. Verdict Model

| Verdict | 意義 | 使用時機 |
|---|---|---|
| `APPROVED` | 足夠安全，可接受 | 不再有 blocking governance 或 correctness 問題 |
| `CHANGES_REQUESTED` | 必須修正 | 存在明確 blocking issue |
| `ESCALATED` | 需要人類決策 | review 後仍有重大 risk / trade-off ambiguity |

### 2.1 Finding Levels

| Level | 意義 |
|---|---|
| `BLOCKING` | 必須修掉的 governance / correctness / safety 問題 |
| `WARNING` | 必須顯性指出的風險、技術債、或弱 evidence |
| `SUGGESTION` | 不阻擋的改善建議 |

不要把 `ESCALATED` 和 `BLOCKING` 混為一談。  
Escalation 是給仍未解決的重大歧義，不只是 defect。

---

## 3. Mandatory Audit Checklist

### 3.1 Boundary and Architecture

檢查：
- domain code 是否碰到 forbidden I/O、UI、OS、或 native concern
- external / native model 介入時，ACL 使用是否合理
- 變更是否與 ADR 或 boundary rule 衝突

### 3.2 Physical and Native Safety

若涉及 native interop，檢查：
- memory ownership 是否明確
- 需要時 ABI layout 是否明確
- panic / fail-fast 與 recoverable error handling 是否一致

若不涉及 native interop，標記 `N/A`。

### 3.3 Quality and Verification

檢查：
- evidence 是否符合 task risk
- failure path 在適用時是否有被考慮
- verification 是否鎖定 behavior，而不是 implementation trivia
- legacy refactor 是否真的先確認 baseline buildability

### 3.4 Thread Safety and Async Safety

若碰到 UI 或 async path，檢查：
- 影響 UI 的更新是否留在正確 thread
- async failure path 是否有處理

若無關，標記 `N/A`。

### 3.5 Dirty Worktree and Scope Hygiene

若 implementation 或 review 當時 worktree 是 dirty，檢查：
- unrelated dirty file 是否沒有被靜默混進 scope
- touched-file overlap 是否已處理或明確 escalate
- commit / review boundary 是否仍然可理解

---

## 4. Knowledge Base Cross-Check

在給 verdict 前，檢查 `memory/03_knowledge_base.md`：
1. 有沒有 anti-pattern match
2. 有沒有已記錄過的 regression pattern

若已知 anti-pattern 再次出現，要明確點出來。

---

## 5. Legacy Refactor Review Addendum

對 legacy repo、refactor、rollback、或 baseline reset，review 還必須檢查：
- 所宣稱的 baseline 是否真的用 authoritative build path 驗過
- canonical toolchain 是否已辨識
- 這次變更是否在 baseline 不穩定時，仍被包裝成安全 refactor

若 baseline 未驗證：
- 不要把結果描述成 clean refactor
- 至少出一個 `WARNING`
- 若結論依賴 baseline 穩定，則應 escalate

---

## 6. Review Output Format

每次 review 回應都應包含：

```markdown
### [Decision Summary]
**Verdict**: APPROVED | CHANGES_REQUESTED | ESCALATED
**Risk Level**: Low | Medium | High

### Governance Audit
- Architecture: ...
- Native Safety: ... | N/A
- Test Integrity: ...
- Thread Safety: ... | N/A
- Baseline Status: Stable | Unverified | Unstable | N/A

### Technical Findings
1. [BLOCKING|WARNING|SUGGESTION] Title
   - Location: `path:line`
   - Evidence: ...
   - Rule Reference: ...
   - Fix Required / Reasoning: ...

### Knowledge Base Alignment
- Anti-patterns checked: N
- Regression notes checked: N
- Result: Pass | Conflict Found
```

每個 non-trivial finding 都必須指明：
- location
- evidence
- rule reference

---

## 7. Post-Review Memory Actions

發出 verdict 後：

1. 將完整 review record append 到 `memory/04_review_log.md`
2. 在 `memory/01_active_task.md` 加一行摘要
3. 若發現新的 anti-pattern，記到 `memory/03_knowledge_base.md`

`memory/01_active_task.md` 應保持精簡，不要把完整 findings 全倒進去。

---

## 8. C++ Build Boundary Addendum

當 review 碰到 C++ project file、header layout、或 build configuration 時，套用這段補充。

硬檢查：
- `AdditionalIncludeDirectories` 或同類設定，不得指向 peer-project 的 private tree
- cross-project private header 不得因為 build pass 就被合理化
- 若 header 是 shared，應放在有明確 ownership 的 shared boundary layer

這是 boundary issue，不是 style issue。

---

## 9. Final Principle

> **沒有指名 evidence 的 review，不是有效 review。**
> **結論若依賴歧義，用 escalation；違規若已具體成立，用 blocking finding。**
