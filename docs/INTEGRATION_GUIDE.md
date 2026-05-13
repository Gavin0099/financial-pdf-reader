# INTEGRATION_GUIDE.md - 導入指南

> **Version**: v1.0  
> **Last Updated**: 2026-04-10

這份文件說明如何把 `ai-governance-framework` 導入到 consuming repo。  
它的重點是 **repo-level governance integration**，不是 generic platform setup。

## 1. 導入後會得到什麼

導入 framework 後，consuming repo 會得到：

- canonical governance baseline
- memory scaffold
- governance markdown pack
- governance rule pack
- drift / readiness / onboarding surface
- bounded session workflow 與 closeout path

這不代表 consuming repo 立刻變成完整 AI runtime platform；它只是有了可被檢查、可被採用、可被 reviewer 理解的治理骨架。

## 2. 先決條件

建議 consuming repo 至少有：

- 正確的 framework source（canonical repo 或 pinned submodule）
- 可執行的 Python 環境
- repo root 可寫入：
  - `.governance/`
  - `memory/`
  - `governance/`

## 3. canonical source

建議使用：

```text
https://github.com/Gavin0099/ai-governance-framework.git
```

不要把落後 fork 當成正常版本差異。  
`external_repo_readiness.py`、`external_repo_version_audit.py`、`external_repo_onboarding_report.py` 都會把 framework source 是否 canonical 顯式浮出來。

## 4. submodule 導入

```powershell
git submodule add https://github.com/Gavin0099/ai-governance-framework.git additional/ai-governance-framework
git submodule update --init --recursive
```

submodule 的版本是 parent repo 的決策。  
framework checkout 更新，不等於 parent repo 已正式接受新的 pinned version。

## 5. adopt 流程

在 consuming repo root 執行：

```powershell
python additional/ai-governance-framework/governance_tools/adopt_governance.py --target . --framework-root additional/ai-governance-framework
```

adopt 會：

- 建立 `.governance/baseline.yaml`
- 複製 `AGENTS.base.md`
- 建立或修補 `contract.yaml`
- 建立 root `PLAN.md`
- 建立 `memory/01~04`
- 複製 `governance/*.md`
- 複製 `governance/rules/**`

## 6. adopt 後的最小檢查

至少確認以下檔案存在：

- `.governance/baseline.yaml`
- `AGENTS.base.md`
- `contract.yaml`
- `PLAN.md`
- `memory/01_active_task.md`
- `memory/02_tech_stack.md`
- `memory/03_knowledge_base.md`
- `memory/04_review_log.md`
- `governance/TESTING.md`
- `governance/ARCHITECTURE.md`
- `governance/rules/common/core.md`

## 7. readiness / drift / smoke

### Drift

```powershell
python additional/ai-governance-framework/governance_tools/governance_drift_checker.py --repo . --framework-root additional/ai-governance-framework
```

### Readiness

```powershell
python additional/ai-governance-framework/governance_tools/external_repo_readiness.py --repo . --framework-root additional/ai-governance-framework --format human
```

### Quickstart / runtime surface smoke

```powershell
python additional/ai-governance-framework/governance_tools/quickstart_smoke.py
python additional/ai-governance-framework/governance_tools/runtime_surface_manifest_smoke.py --format human
```

目標是確認：

- 沒有 critical drift
- `memory_schema_status` 不是 partial
- framework source 是 canonical
- runtime surface 基本一致

## 8. memory 與 closeout 要怎麼理解

framework 目前已補上：

- memory scaffold
- memory sync signal
- memory closeout visibility

但要注意：

- adopt 只建立 scaffold，不會保證每次工作都自動寫入 memory
- `session_end` 需要真的進 shared path，closeout 才會被看見
- `memory_closeout` 目前補的是可見性，不是 promotion 擴權

你現在至少可以看到：

- `candidate_detected`
- `promotion_considered`
- `decision`
- `reason`

也就是說，「為什麼這次 memory 沒更新」不再是黑箱。

## 9. rule pack 與 contract

`contract.yaml` 應正確維護：

- `rule_roots`
- `documents`
- repo-local risk / language / domain 設定

adopt 後，至少應讓 `documents:` 指向像這些檔案：

- `governance/TESTING.md`
- `governance/ARCHITECTURE.md`

否則 agent 雖然有 baseline，但不會自然讀到 repo-level testing / architecture guardrails。

## 10. starter-pack 與完整 adopt 的差別

如果專案還很小，只需要最小治理起點，可以先看：

- [examples/starter-pack/README.md](../examples/starter-pack/README.md)
- [governance_tools/upgrade_starter_pack.py](../governance_tools/upgrade_starter_pack.py)

但 starter-pack 只提供：

- `SYSTEM_PROMPT.md`
- `PLAN.md`
- `memory/01_active_task.md`
- 基本 adapter files

它**不等於**完整 framework adopt，也不會自動提供：

- drift checker
- readiness surface
- governance/rules pack
- closeout / audit 閉環

## 11. 常見錯誤

### 只有 submodule，沒有 adopt

這種情況通常會缺：

- `.governance/baseline.yaml`
- `AGENTS.base.md`
- `memory scaffold`

### memory schema partial

例如只有 `02_tech_stack.md`，卻沒有 `01/03/04`。  
現在 framework 會把這種情況辨識成 partial，不會再誤當成 complete。

### 使用錯誤 framework source

如果 repo 指向落後 fork，雖然看起來是同一套 framework，實際上可能少掉較新的 signal、closeout、readiness 或 audit 修正。

## 12. 最小導入順序

1. 確認 source
2. 加入 submodule 或 clone
3. 執行 adopt
4. 確認 baseline / memory / governance pack 存在
5. 跑 drift / readiness / smoke
6. 再開始看 runtime hook、closeout、reviewer surface

## 13. 一句話總結

> 導入 consuming repo 的目標，不是把 framework 檔案堆進 repo，而是把 repo 帶到一條可被檢查、可被 reviewer 理解、也能逐步進入 bounded governance runtime 的 adoption path。
