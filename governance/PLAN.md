---
audience: agent-runtime
authority: canonical
can_override: false
overridden_by: ~
default_load: always
---

# PLAN.md 模板與治理說明

> **這是 repo 的規劃單一真相來源範本。**
> 真正提供 AI 與 reviewer 使用的專案規劃檔，應放在 repo root 的 [`PLAN.md`](../PLAN.md)。
> 本文件的角色是說明 PLAN 應該長什麼樣，以及為什麼需要它。

---

## 1. PLAN.md 的角色

`PLAN.md` 不是 README，也不是任意備忘錄。它是專案目前規劃狀態的 canonical source，負責：
- 當前 focus 是什麼
- 目前在第幾個 phase
- 這個 phase 明確要做什麼
- 哪些事情刻意不做
- AI 在這個 phase 中怎麼判斷 scope 與 next step

如果沒有 `PLAN.md`，AI 很容易：
- 看見 backlog 就一路往外擴
- 把相鄰工程工作與 feature expansion 混在一起
- 在沒有 anti-goal 的情況下誤解使用者意圖

---

## 2. PLAN 的基本原則

### 2.1 Single Source of Truth

對 planned work、phase status、anti-goals 而言：

```text
PLAN.md = 單一真相來源
```

其他文件可以補充，但不應各自維護另一份長期規劃，並讓它和 `PLAN.md` 漂移。

### 2.2 AI 會怎麼用它

AI 讀 `PLAN.md` 主要是為了回答：
- 當前 phase 是什麼
- 哪些 backlog 還沒輪到
- 哪些工作雖然看似合理，但被 anti-goals 明確排除
- 使用者新要求屬於：當前 phase、相鄰工程、還是 feature expansion

### 2.3 它不是萬能阻擋器

`PLAN.md` 管的是 feature priority，不是用來阻止所有相鄰工程活動。

預設仍屬於可直接處理的相鄰工程包括：
- build
- test
- debugging
- review
- commit preparation
- documentation synchronization
- bounded governance analysis

只有當這些工作跨到 hard boundary、risk gate、或 feature expansion，才需要 escalate。

---

## 3. Mandatory Structure

每個 repo 的 root `PLAN.md` 至少應包含以下區塊：

```markdown
# PLAN.md - [Project Name]

> **Project Type**: [type]
> **Primary Language**: [language]
> **Task Level**: L1 / L2 / L3
> **Planning Window**: [start] ~ [end]
> **Last Updated**: YYYY-MM-DD
> **Owner**: [name]
> **Freshness**: Sprint (7d) | Phase (30d) | Custom (Nd)

---

## 專案目標

## 當前階段與 phase 狀態

## 當前 Sprint / 當前工作

## Backlog

## Anti-Goals

## AI 執行規則

## Gate / 完成條件

## 已知問題或技術債（選填）

## 里程碑

## 更新紀錄
```

缺少這些基本區塊，AI 就比較難穩定判斷目前「該做什麼」與「不該做什麼」。

---

## 4. Header 欄位

`Last Updated`、`Owner`、`Freshness` 必須在 header 中明示。

```markdown
> **Last Updated**: YYYY-MM-DD
> **Owner**: <owner>
> **Freshness**: Sprint (7d)
```

Freshness policy：

| Policy | 說明 | 判定 |
|---|---|---|
| `Sprint (7d)` | 以 sprint 為單位 | 超過 7 天可視為 stale |
| `Phase (30d)` | 以 phase 為單位 | 超過 30 天可視為 stale |
| `Custom (Nd)` | 自定義天數 | 超過 N 天可視為 stale |

`governance_tools/plan_freshness.py` 會使用這些欄位做 freshness 檢查。

---

## 5. 內容區塊說明

### 5.1 專案目標

這裡要簡短說清楚：
- 專案在解什麼問題
- bounded context 是什麼
- 明確不負責什麼

至少應回答：
- responsible for X
- NOT responsible for Y

### 5.2 當前階段與 phase 狀態

應清楚標出：
- phase 序列
- 當前 phase
- 已完成 / 進行中 / 尚未開始

範例：

```markdown
## 當前階段與 phase 狀態

- [x] Phase A: 基礎建置
- [>] Phase B: 核心功能整合
- [ ] Phase C: 驗證與收斂
- [ ] Phase D: 發版準備

**Current Phase**: Phase B - 核心功能整合
```

### 5.3 當前 Sprint / 當前工作

這裡要回答：
- 這個 sprint / 這個 phase 現在真正要做什麼
- 哪些任務是當前 focus
- 哪些工作雖存在，但不屬於 current sprint

### 5.4 Backlog

Backlog 應至少分成：
- P0
- P1
- P2

避免把所有想法平鋪成一個巨大清單，讓 AI 誤以為都可以立刻開始做。

### 5.5 Anti-Goals

這是最重要的區塊之一。它明確說明：
- 這個 phase / sprint 刻意不做什麼
- 哪些看似合理的延伸其實不屬於目前 scope

如果沒有 anti-goals，AI 很容易把「可以做」誤解成「現在就該做」。

### 5.6 AI 執行規則

這裡應清楚告訴 AI：
- 遇到不在 current phase 的工作時怎麼判斷
- 什麼時候可以視為 adjacent engineering work
- 什麼時候要 escalate

### 5.7 Gate / 完成條件

對 L2+ repo，建議列出：
- phase gate
- build / test / validation 最低要求
- release 或 reviewer-facing completion condition

### 5.8 里程碑與更新紀錄

至少應留下：
- milestone 名稱
- 預計日期
- 當前狀態
- update log

這能讓 reviewer 與未來 session 看得出規劃是活的，不是一次性文件。

---

## 6. AI 使用規則

AI 在讀 `PLAN.md` 時，至少要做這些事：
- 對照當前請求是否落在 current phase
- 對照 anti-goals，避免默默擴 scope
- 對照 backlog priority，避免跳過明顯更重要的項目
- 在不確定時，提出選項而不是自行重排 roadmap

若 `PLAN.md` 結構明顯不完整、欄位缺失、或 freshness 過舊，應明說這個風險，而不是假裝規劃仍然可靠。

---

## 7. L1 / L2 / L3 適用建議

### L1

可用較輕量的 phase / sprint 結構，但仍應具備：
- 專案目標
- 當前工作
- backlog
- anti-goals
- AI 執行規則

### L2

應完整具備本文件列出的 mandatory structure。

### L3

除了完整結構，還建議補：
- ADR 對應
- 明確 phase gate
- 更清楚的 reviewer / release criteria

---

## 8. 最小範例

```markdown
# PLAN.md - Example Project

> **Project Type**: tooling
> **Primary Language**: Python
> **Task Level**: L1
> **Planning Window**: 2026-04-01 ~ 2026-04-30
> **Last Updated**: 2026-04-08
> **Owner**: example-owner
> **Freshness**: Sprint (7d)

## 專案目標

這個 repo 負責生成與驗證治理 artifact。

**Bounded Context**:
- governance toolchain
- status generation
- repo-local validation

**Not Responsible For**:
- 外部部署系統
- 非 repo-local production orchestration

## 當前階段與 phase 狀態

- [x] Phase A: baseline 建立
- [>] Phase B: runtime hardening
- [ ] Phase C: adoption cleanup

**Current Phase**: Phase B - runtime hardening

## 當前 Sprint / 當前工作

- closeout audit status surface
- adoption source audit
- docs 中文主敘事清理

## Backlog

### P0
- consuming repo readiness gaps

### P1
- additional release surface cleanup

### P2
- optional comparative docs refinement

## Anti-Goals

- 不在這一輪做 full multi-agent orchestration
- 不把 advisory 直接升格成 verdict authority

## AI 執行規則

- 當前 phase 外的 feature expansion 先 escalate
- bounded docs / test / status cleanup 可直接做
```

---

## 9. Final Principle

`PLAN.md` 的目的不是把 repo 寫得很完整，而是讓 AI 與 reviewer 對「現在該做什麼、刻意不做什麼」有同一張圖。

如果這張圖不存在，擴張幾乎一定會發生。
