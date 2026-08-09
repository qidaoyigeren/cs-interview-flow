# 基础题：Go interface 的 nil 陷阱

## 问题

为什么一个保存了 nil 指针的 interface 与 nil 比较可能为 false？怎样避免错误判断？

## 参考要点

- interface 包含动态类型和动态值，只有两者都为空才等于 nil
- 类型信息存在而动态值为 nil 时 interface 本身非 nil
- API 尽量返回明确 nil interface，调用处按约定判断错误
- 反射判断需谨慎且通常不应替代清晰的类型设计

## 追问

1. 这个机制最常见的误区是什么？
2. 在什么边界下应该选择另一种方案？
