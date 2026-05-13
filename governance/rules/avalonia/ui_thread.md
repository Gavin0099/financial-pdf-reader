# Avalonia UI Thread

- UI control mutation 與 `PropertyChanged` side effect 必須在 `Dispatcher.UIThread` 或等價的安全邊界上執行。
- ViewModel 不應把跨 thread 的 UI 修補邏輯藏成 convenience shortcut。
- 若某條流程依賴 UI-thread affinity，測試應把這個依賴顯性化。
