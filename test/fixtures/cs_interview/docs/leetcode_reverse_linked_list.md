# LeetCode 题解：反转链表（Reverse Linked List）

## 题干
给你单链表的头节点 head，请你反转链表，并返回反转后的链表。

## 约束
- 链表中节点的数目范围是 [0, 5000]
- -5000 <= Node.val <= 5000
- 进阶：链表可以选用迭代或递归方式完成反转，你能否用两种方法解决这道题？

## 标准解法（迭代三指针）
初始化 prev = null，curr = head；循环中保存 next = curr.next，将 curr.next 指向 prev，然后 prev、curr 各前进一步；循环结束后返回 prev。
递归解法：若 head 为空或 head.next 为空返回 head；递归反转子链表，将 head.next.next 指向 head，head.next 置空，返回新的头。

- 时间复杂度：O(n)，每个节点访问一次
- 空间复杂度：迭代 O(1)；递归 O(n)（栈深度）

## 可见样例
输入: head = [1,2,3,4,5] → 输出: [5,4,3,2,1]
输入: head = [1,2] → 输出: [2,1]
输入: head = [] → 输出: []

## 隐藏测试
输入: head = [1] → 输出: [1]（单节点）
输入: head = [1,2,3,4,5,6,7,8,9,10] → 输出: [10,9,8,7,6,5,4,3,2,1]（长链表）
输入: head = [-5,-4,-3] → 输出: [-3,-4,-5]（负值）

## 函数签名
class ListNode { val; next; } function reverseList(head: ListNode | null): ListNode | null
