# Go 基础：context 取消传播与生命周期

## 问题

解释 Go `context.Context` 的取消传播、deadline 和 value 使用边界，并说明怎样避免泄漏。

## 参考要点

- context 构成父子树；父 context 取消时，派生子 context 一并取消。
- `WithCancel`、`WithTimeout`、`WithDeadline` 返回的 cancel 应及时调用，释放 timer 和子节点引用。
- context 应作为请求范围的第一个参数传递，不应存进长期对象，也不应用于可选业务参数。
- 阻塞操作需要主动监听 `Done()`，仅把 context 传进函数但函数不检查它没有作用。
- `Value` 适合请求追踪、鉴权等跨层元信息，key 应避免碰撞，不适合承载大对象。

## 可追问

- `context.Background()` 与 `context.TODO()` 的语义差异是什么？
- 数据库和 HTTP 客户端怎样真正响应 context 取消？
- 取消是错误还是控制信号，日志级别应如何选择？

