# 面经：Go channel 死锁排查（一面）

## 背景
某大厂 Go 后端一面，面试官给出一个会死锁的 channel 示例代码，让候选人指出死锁原因并修复。

## 题目示例
无缓冲 channel 在主 goroutine 中直接发送数据，没有接收方，导致 all goroutines are asleep - deadlock。

## 候选人作答摘要
候选人指出：无缓冲 channel 的发送会阻塞直到有接收方就绪；主 goroutine 发送而无人接收必然死锁。修复方案：改用带缓冲的 channel，或启动一个 goroutine 去接收，或调整发送/接收的配合顺序。候选人进一步补充了 select + default 的非阻塞发送技巧。

## 面试官评分要点
- 正确指出无缓冲 channel 阻塞语义（命中）
- 给出至少两种修复方案并解释 trade-off（命中）
- 能扩展到有缓冲 channel 的容量与阻塞关系（加分）
- 能说明 select 在超时/非阻塞场景的用法（加分）

## 追问链
- 追问 1：有缓冲 channel 发送/接收分别在何时阻塞？
- 追问 2：channel 关闭后再发送/再接收会发生什么？

## 录用结论
候选人基础扎实，死锁定位准确，通过一面。
