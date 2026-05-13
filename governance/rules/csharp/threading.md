# C# Threading Safety

- UI state change 必須發生在正確的 UI thread 或 dispatcher boundary。
- 除了明確的 event-handler boundary 之外，不要把 `async void` 當成可接受預設。
- 沒有同步策略的 cross-thread mutation，是 governance violation，不是 style issue。
