# MySQL 基础：MVCC、快照读与当前读

## 问题

InnoDB 如何利用 MVCC 实现一致性读？可重复读为什么仍然需要 next-key lock？

## 参考要点

- 聚簇记录包含事务相关隐藏字段，历史版本通过 undo log 形成版本链。
- Read View 依据活跃事务集合和事务 ID 判断某个版本对当前事务是否可见。
- 普通 `SELECT` 通常是快照读；`SELECT ... FOR UPDATE`、更新和删除是当前读。
- 可重复读的快照读依靠固定 Read View 保持一致视图；当前读需要锁定最新记录。
- next-key lock 组合记录锁与间隙锁，用于阻止当前读范围内插入造成的幻读。

## 可追问

- 读已提交和可重复读创建 Read View 的时机有何不同？
- 长事务为什么会导致 undo 膨胀？
- 唯一索引等值命中时 next-key lock 如何退化？

