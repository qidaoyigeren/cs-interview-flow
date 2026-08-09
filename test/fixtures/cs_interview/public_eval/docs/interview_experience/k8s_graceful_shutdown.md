# 场景题：Kubernetes 发布时出现少量 502 和重复任务

## 题目

Go 服务滚动发布时会出现少量 502，同时后台任务偶尔重复执行。服务运行在 Kubernetes 中，你会怎样设计优雅下线？

## 评分点

- 收到 SIGTERM 后先将 readiness 置为失败，使新流量停止进入。
- 等待负载均衡和端点传播，再关闭 HTTP listener，并为在途请求设置有界 drain 时间。
- 停止领取新任务，对已领取任务使用幂等键、租约或可恢复 checkpoint。
- `terminationGracePeriodSeconds` 要覆盖传播、drain 和清理预算，不能无限等待。
- 检查 preStop、连接复用、长连接、消费组 rebalance 和任务可见性超时。

## 追问

1. 只调用 `http.Server.Shutdown` 为什么仍可能有 502？
2. 如果任务执行超过下线预算，如何在不中断一致性的前提下转移？
3. 如何用发布监控证明修复有效？

