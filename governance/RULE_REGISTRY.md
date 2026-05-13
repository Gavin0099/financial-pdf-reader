---
audience: agent-runtime
authority: canonical
default_load: always
---

# Governance Rule Registry

這份文件是 valid rule pack name 的 authoritative registry。
任何未列在這裡的 rule pack，都會觸發 `Unknown rule packs: [...]` 類錯誤。

它可被 `governance_tools/rule_classifier.py` machine-read。

rule pack 的選擇時機在 session start，依據：
- `repo_type`: firmware | product | service | tooling
- `task_type`: general | refactor | release | review | onboarding | test
- `load_mode`: always | context_aware

`always` pack 每次 session 都會載入，不受 context 影響。
`context_aware` pack 只有在 `repo_type` 與 `task_type` 匹配時才啟用。

---

## Valid Rule Packs（Quick Reference）

| Pack Name | Description | Typical Use |
|---|---|---|
| `common` | 通用 baseline 規則 | 所有 repo（永遠載入） |
| `cpp` | C / C++ 規則 | firmware、driver、embedded repo |
| `csharp` | C# 規則 | .NET、Avalonia repo |
| `kernel-driver` | kernel / driver 特定限制 | KDC 與同類 driver repo |
| `python` | Python 規則 | service、tooling repo |
| `refactor` | refactoring 指引 | 任何進行 refactor 的 repo |
| `release` | release checklist 規則 | release session |
| `review_gate` | review gate checklist | review session |
| `swift` | Swift 規則 | iOS / macOS repo |
| `avalonia` | Avalonia UI framework 規則 | desktop app repo |
| `typescript` | TypeScript / Node.js 規則 | product repo |
| `electron` | Electron IPC 安全規則 | Electron app repo |
| `nextjs` | Next.js routing / rendering 規則 | Next.js product repo |
| `supabase` | Supabase RLS 與 auth 規則 | Supabase-backed repo |
| `firmware_isr` | ISR safety 與 RTOS 限制 | firmware repo |

---

## Rule Packs（Machine-Readable Metadata）

### common

```yaml
name: common
load_mode: always
repo_type: [all]
task_type: [all]
risk_level: [all]
description: "Core coding standards; loaded in every session"
```

### refactor

```yaml
name: refactor
load_mode: context_aware
repo_type: [all]
task_type: [refactor]
risk_level: [all]
description: "Refactoring patterns; activated when task_type=refactor"
```

### release

```yaml
name: release
load_mode: context_aware
repo_type: [all]
task_type: [release]
risk_level: [all]
description: "Release checklist rules; activated when task_type=release"
```

### typescript

```yaml
name: typescript
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "TypeScript/Node.js best practices for product repos"
```

### python

```yaml
name: python
load_mode: context_aware
repo_type: [service, tooling]
task_type: [all]
risk_level: [all]
description: "Python coding standards for service and tooling repos"
```

### electron

```yaml
name: electron
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "Electron IPC security and process isolation rules"
```

### avalonia

```yaml
name: avalonia
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "Avalonia UI component and threading rules"
```

### cpp

```yaml
name: cpp
load_mode: context_aware
repo_type: [firmware, product]
task_type: [all]
risk_level: [all]
description: "C++ memory safety and RAII rules"
```

### csharp

```yaml
name: csharp
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "C# async patterns and null safety rules"
```

### swift

```yaml
name: swift
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "Swift value-type safety and concurrency rules"
```

### nextjs

```yaml
name: nextjs
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "Next.js routing, data fetching, and rendering rules"
```

### supabase

```yaml
name: supabase
load_mode: context_aware
repo_type: [product]
task_type: [all]
risk_level: [all]
description: "Supabase RLS policies and auth integration rules"
```

### firmware_isr

```yaml
name: firmware_isr
load_mode: context_aware
repo_type: [firmware]
task_type: [all]
risk_level: [all]
description: "ISR safety, RTOS constraints, and HAL boundary rules for firmware repos"
```

### kernel-driver

```yaml
name: kernel-driver
load_mode: context_aware
repo_type: [firmware]
task_type: [all]
risk_level: [all]
description: "Kernel/driver-specific constraints for KDC and similar driver repos"
```

### review_gate

```yaml
name: review_gate
load_mode: context_aware
repo_type: [all]
task_type: [review]
risk_level: [all]
description: "Review gate checklist; activated for review task sessions"
```

---

## How Rule Packs Are Selected

rule pack 由 `adopt_governance.py` 的 `_get_default_rule_packs()` 根據偵測到的 repo type 選出，或由 `--rules` CLI argument 明確指定。

若要在程式中列舉有效選項，使用：
- `get_context_aware_rule_packs()`
- `available_rule_packs()`

這兩者都位於 `governance_tools/rule_pack_loader.py`。

---

## 為什麼 `onboarding` 不是合法 rule pack

`onboarding` **不是** rule pack 名稱。若你看到：

```text
Unknown rule packs: ['onboarding']
```

這表示 `adopt_governance.py` 或某個呼叫它的 script，把 `"onboarding"` 當成 rule pack 傳入。

正確修法是：
- 移除這個值
- 改用 `get_context_aware_rule_packs()`
- 或從上表中選擇明確合法的 pack

**對 onboarding session 的正確做法：**

| Repo Type | Rule Packs |
|---|---|
| Firmware / driver repo | `['common', 'cpp', 'kernel-driver']` |
| Product repo (TypeScript) | `['common']` |
| Service repo (Python) | `['common', 'python']` |
| Unknown | `['common']` |

onboarding session 使用的 rule pack，應與該 repo type 的一般 L1 session 一致；不存在特殊的 `onboarding` rule pack。
