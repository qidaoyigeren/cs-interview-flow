# 场景题：请求取消后 goroutine 数量持续增长

## 题目

一个 Go 聚合接口会并发请求三个下游。压测中请求超时后，接口虽然已经返回，但进程的 goroutine 数持续增长。你会怎样定位并修复？

## 评分点

- 使用 goroutine profile、trace 或监控确认泄漏栈，而不是只调大超时。
- 将请求 context 传递到所有下游调用，并在 worker 的 select 中监听 `ctx.Done()`。
- 检查无接收方的 channel 发送、未停止的 ticker、无退出条件的重试循环。
- 明确谁负责关闭 channel；发送方关闭，接收方不能随意关闭。
- 修复后用稳定压测与 goroutine 基线验证没有持续增长。

## 追问

1. 如果结果 channel 是无缓冲的，而主请求已经返回，worker 会发生什么？
2. `context.WithTimeout` 创建后为什么仍要调用 cancel？
3. 怎样避免“为每个请求创建无限 goroutine”的并发放大？

## 常见错误

- 只增加 channel 缓冲，掩盖但不消除生命周期错误。
- 在多个 goroutine 中竞争关闭同一个 channel。
- 把 context 存进长期结构体并跨请求复用。

