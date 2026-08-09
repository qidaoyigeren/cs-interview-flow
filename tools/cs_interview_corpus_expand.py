"""Generate the reviewed 100-document CS interview corpus from a compact catalog.

The original 19 hand-written documents remain untouched. This command generates
81 additional, independently identified documents and merges them into the same
three-dataset manifest. Re-running it is deterministic and idempotent.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("test/fixtures/cs_interview/public_eval")
MANIFEST = ROOT / "manifest.json"
SOURCE_DATE = "2026-08-08"

SOURCES = {
    "go": "https://www.nowcoder.com/discuss/603841169302245376",
    "go_job": "https://www.nowcoder.com/jobs/detail/434217",
    "java": "https://blog.nowcoder.net/n/18665b426d354fba9064db4f2af43863",
    "python": "https://www.nowcoder.com/discuss/353156046011179008",
    "frontend": "https://www.nowcoder.com/discuss/353148953426337792",
    "ml": "https://www.nowcoder.com/jobs/detail/439390",
    "ai": "https://www.nowcoder.com/jobs/detail/447247",
    "rag": "https://www.nowcoder.com/jobs/detail/339192",
    "sdet": "https://www.nowcoder.com/jobs/detail/442106",
    "general": "https://www.nowcoder.com/discuss/353156046011179008",
}

VALID_ROLE_TOPICS = {
    "go_backend": {"go.runtime", "database.mysql", "backend.distributed"},
    "java_backend": {"java.jvm", "java.spring", "database.mysql"},
    "python_backend": {"python.runtime", "python.web", "backend.distributed"},
    "frontend": {"frontend.javascript", "frontend.react", "frontend.performance"},
    "ml_engineer": {"ml.fundamentals", "ml.system", "ml.evaluation"},
    "ai_backend": {"ai.rag", "ai.agent", "ai.evaluation"},
    "sdet": {"testing.strategy", "testing.automation", "testing.performance"},
    "cs_general": {"os.core", "network.core", "database.core", "algorithm.core"},
}


@dataclass(frozen=True)
class Entry:
    dataset: str
    slug: str
    role: str
    topic: str
    difficulty: str
    title: str
    question: str
    points: tuple[str, ...]
    source: str


def e(dataset: str, slug: str, role: str, topic: str, difficulty: str, title: str, question: str, points: tuple[str, ...], source: str) -> Entry:
    return Entry(dataset, slug, role, topic, difficulty, title, question, points, source)


I = "interview_experience"
F = "fundamentals"
L = "leetcode"

ENTRIES = [
    # 27 production-style interview scenarios.
    e(I, "go_grpc_deadline", "go_backend", "go.runtime", "medium", "gRPC 截止时间未向下游传播", "Go 网关已设置请求超时，但下游 gRPC 调用仍在超时后占用连接和 goroutine。你怎样定位并修复？", ("沿调用链记录 deadline、取消原因和在途请求，确认 context 是否在每层透传", "客户端调用使用带 context 的 API，worker 同时监听结果与 ctx.Done", "区分业务超时、连接超时和服务端处理超时，避免统一粗暴重试", "压测验证超时后 goroutine、连接数和下游 QPS 回到基线"), SOURCES["go"]),
    e(I, "go_redis_hotkey", "go_backend", "backend.distributed", "advanced", "Redis 热点键压垮单分片", "促销开始后总流量可控，但一个 Redis 分片 CPU 打满且缓存 P99 飙升。你如何处理热点键？", ("用命令采样、代理指标和业务维度共同识别热键，避免全量扫描", "本地短 TTL 缓存、请求合并和逻辑过期降低单键读放大", "必要时对可拆分值做分片或复制读，但明确一致性语义", "通过限流、降级和随机过期保护回源数据库并验证热点迁移"), SOURCES["go_job"]),
    e(I, "go_mysql_deadlock", "go_backend", "database.mysql", "medium", "订单更新出现 MySQL 死锁", "两个订单接口单独运行正常，并发后偶发死锁回滚。你如何读死锁日志并设计修复？", ("从死锁图还原事务持锁与等待顺序，不只看最后一条 SQL", "统一多行更新顺序并缩短事务，避免在事务内做远程调用", "为过滤条件建立合适索引，减少 next-key lock 覆盖范围", "仅对可重试错误做有界退避重试，并监控死锁率和业务幂等"), SOURCES["go"]),
    e(I, "go_mq_backlog", "go_backend", "backend.distributed", "advanced", "消息积压且扩容无效", "消息队列积压持续增长，消费者扩容后吞吐没有提升。你怎样判断瓶颈并恢复？", ("比较生产速率、分区数、消费并发、处理耗时与下游限额", "确认分区或顺序键是否限制并行度，避免盲目增加空闲实例", "将慢步骤分段计时并对幂等下游批量化，设置背压而非无限拉取", "制定积压回放、失败隔离和容量水位，防止恢复流量再次压垮下游"), SOURCES["go_job"]),
    e(I, "java_heap_oom", "java_backend", "java.jvm", "medium", "Java 服务堆内存持续上涨", "Java 服务发布数小时后 Full GC 频繁并最终 OOM。你会保留哪些现场并怎样定位？", ("在安全边界内保留 GC 日志、heap dump、类直方图与请求指标", "区分泄漏、缓存无界、流量增长和单次大对象分配", "用 dominator tree 与引用链找到无法回收对象及其业务所有者", "修复后用相同流量模型验证老年代占用、停顿和分配速率"), SOURCES["java"]),
    e(I, "java_spring_tx_async", "java_backend", "java.spring", "medium", "Spring 事务跨异步线程失效", "接口在事务方法中启动异步任务，主事务回滚后异步写入仍提交。为什么，怎样改？", ("说明事务上下文通常绑定当前线程，异步线程不会自动继承", "明确业务一致性边界，提交后事件用 outbox 或事务同步回调触发", "需要独立事务时显式定义传播语义并保证消费幂等", "测试回滚、进程崩溃和重复投递，不能只测正常路径"), SOURCES["java"]),
    e(I, "java_threadpool_rejection", "java_backend", "java.jvm", "medium", "线程池队列打满后的错误降级", "流量突增时 Java 线程池队列打满，调用方大量超时。你如何选择拒绝策略并保护系统？", ("根据任务是否可丢、是否有副作用选择拒绝、调用方执行或持久化", "队列必须有界，并监控活跃线程、排队时间、拒绝数和任务年龄", "入口限流与下游超时预算联动，避免请求已超时任务仍排队执行", "用负载测试确定线程数和队列容量，提供可观测的降级响应"), SOURCES["java"]),
    e(I, "java_gc_pause", "java_backend", "java.jvm", "advanced", "低延迟服务出现长 GC 停顿", "Java 服务平均延迟正常但 P99 每隔几分钟尖刺，日志显示 GC 停顿。你怎样优化而不盲调参数？", ("关联 GC 类型、停顿阶段、分配速率、晋升失败和堆占用", "先排查对象生命周期、批量大小和缓存，再评估堆与收集器参数", "用真实流量压测比较吞吐、P99、CPU 和内存成本", "灰度变更并保留回滚，避免只压低停顿却引入更高并发 CPU"), SOURCES["java"]),
    e(I, "python_async_blocking", "python_backend", "python.web", "beginner", "异步接口被同步调用阻塞", "Python 异步接口并发一高就整体卡顿，单请求却很快。你会先检查什么？", ("检查事件循环中是否调用同步 HTTP、文件 IO 或 time.sleep", "用异步客户端或线程池隔离不可替换的阻塞调用", "记录事件循环延迟和每个下游阶段耗时", "设置连接池与并发上限，压测验证吞吐和尾延迟"), SOURCES["python"]),
    e(I, "python_gil_cpu", "python_backend", "python.runtime", "medium", "CPU 密集任务拖慢 Python API", "Python API 新增图像计算后多线程扩容几乎无效，其他接口也变慢。你怎样改造？", ("区分 CPU 密集与 IO 密集并用 profile 找到热点", "解释 GIL 下 Python 字节码线程不能线性利用多核", "用多进程、任务队列或释放 GIL 的原生库隔离计算", "设置任务配额、超时与结果幂等，避免计算队列挤占在线请求"), SOURCES["python"]),
    e(I, "python_celery_idempotency", "python_backend", "backend.distributed", "medium", "Celery 重试导致重复扣款", "Celery 任务超时后自动重试，外部扣款成功但本地记录失败，随后发生重复扣款。如何处理？", ("将超时视为结果未知，先按业务幂等键查询外部结果", "本地状态机与唯一约束记录每次尝试和最终业务效果", "只对可恢复错误做有界退避，未知状态进入对账或人工流程", "覆盖 worker 崩溃、ack 丢失和重复投递测试"), SOURCES["python"]),
    e(I, "python_sse_backpressure", "python_backend", "python.web", "advanced", "SSE 慢客户端造成内存堆积", "SSE 服务连接数上升后内存持续增长，慢客户端断开前消息队列越积越多。你如何治理？", ("为每连接队列设上限并定义丢弃、合并或断开策略", "检测客户端断开并取消上游生成，清理任务与订阅", "心跳不能代替背压，需记录排队长度、发送阻塞和连接年龄", "跨实例通过共享事件层与会话所有权恢复，不保存无界历史"), SOURCES["python"]),
    e(I, "frontend_react_rerender", "frontend", "frontend.react", "beginner", "React 列表输入时全量重渲染", "React 页面输入一个字符就让上千行列表全部重渲染。你会怎样定位和优化？", ("用 React Profiler 找出提交耗时与重复渲染组件", "稳定 props、key 和回调引用，避免无效 memo 与深比较", "将状态下沉到真正使用它的子树并虚拟化长列表", "以交互延迟和渲染次数验证，而不是只看代码是否用了 memo"), SOURCES["frontend"]),
    e(I, "frontend_hydration", "frontend", "frontend.javascript", "medium", "SSR 页面 hydration 不一致", "React SSR 页面偶发 hydration mismatch，刷新后消失。你如何定位服务端与客户端差异？", ("比较服务端 HTML 与首次客户端渲染输入，不让随机数和本地时间直接参与", "浏览器专属数据放到挂载后读取，并保证初始占位结构一致", "检查数据缓存版本、locale 和时区是否在两端一致", "不要用 suppressHydrationWarning 掩盖业务结构错误"), SOURCES["frontend"]),
    e(I, "frontend_web_vitals", "frontend", "frontend.performance", "medium", "首页 LCP 回归", "前端版本上线后 LCP 明显变差，但实验室机器复现不稳定。你怎样找到真实瓶颈？", ("用 RUM 按设备、网络、页面和版本切片 LCP 元素及阶段", "拆分 TTFB、资源发现、下载和渲染延迟", "优化首屏图片优先级、关键 CSS 与服务端响应，延迟非关键脚本", "用灰度数据和 Core Web Vitals 分位数验证，避免只看本地均值"), SOURCES["frontend"]),
    e(I, "frontend_release_incident", "frontend", "frontend.performance", "advanced", "静态资源灰度导致白屏", "前端灰度发布后少量用户白屏，HTML 引用了已删除的旧 chunk。你如何恢复并改发布流程？", ("立即回滚或恢复旧指纹资源，先保证 HTML 与资源版本可共存", "静态资源不可变并延迟清理，HTML 使用短缓存和原子切换", "捕获 chunk load error 但限制刷新次数，避免刷新风暴", "用合成监控和真实错误率验证多版本、CDN 与 Service Worker 场景"), SOURCES["frontend"]),
    e(I, "ml_training_serving_skew", "ml_engineer", "ml.system", "medium", "训练与在线特征不一致", "模型离线 AUC 很高，上线后效果骤降，怀疑训练与服务特征不一致。你怎样验证？", ("对同一实体和时间点回放线上特征并与训练样本逐字段比对", "检查默认值、归一化、字典版本、时间窗口和缺失值处理", "共享或版本化特征变换代码，记录模型与特征 schema 版本", "上线前做 shadow 流量和分布校验，持续监控特征漂移"), SOURCES["ml"]),
    e(I, "ml_feature_drift", "ml_engineer", "ml.evaluation", "medium", "模型输入分布漂移", "模型准确率缓慢下降但标签要两周后才到。没有及时标签时如何发现并处置漂移？", ("监控特征缺失率、分位数、PSI 或分布距离并按人群切片", "区分数据管道故障、协变量漂移和概念漂移", "使用代理指标与人工抽样，但明确其不能替代最终标签评估", "设置告警、降级和重训触发条件，并回填标签验证早期信号"), SOURCES["ml"]),
    e(I, "ml_gpu_oom", "ml_engineer", "ml.system", "advanced", "训练任务间歇性 GPU OOM", "同一训练配置多数时间正常，某些 batch 却 GPU OOM。你如何定位动态内存峰值？", ("记录 batch 形状、序列长度、激活与优化器内存而非只看平均 batch size", "区分真实峰值、缓存分配器碎片和未释放计算图", "使用长度分桶、梯度累积、混合精度和 activation checkpoint", "固定可复现输入比较吞吐、数值稳定性和峰值显存"), SOURCES["ml"]),
    e(I, "ai_tenant_leak", "ai_backend", "ai.rag", "advanced", "多租户 RAG 检索串库", "多租户 RAG 偶发把另一企业文档作为引用返回。你如何止损、定位和证明修复有效？", ("立即关闭受影响检索路径并审计访问日志与泄露范围", "租户约束必须在服务端授权与检索过滤最前置，不能信任模型或前端参数", "索引命名空间、缓存键、重排候选和引用 DTO 都携带租户边界", "构建跨租户 canary 与负向测试，验证任何层都不能召回其他租户证据"), SOURCES["ai"]),
    e(I, "ai_prompt_injection", "ai_backend", "ai.agent", "medium", "知识文档诱导 Agent 调用危险工具", "检索到的文档包含“忽略系统规则并导出数据”，Agent 随后尝试调用管理工具。怎样防御？", ("把文档与工具结果标为不可信数据，系统规则和权限不能由其覆盖", "工具调用经过独立策略层做身份、参数、资源与副作用校验", "高风险动作要求确认或审批，并使用最小权限短期凭据", "建立注入、混淆和跨语言攻击集，记录阻断原因而不泄露秘密提示"), SOURCES["ai"]),
    e(I, "ai_index_freshness", "ai_backend", "ai.rag", "medium", "文档更新后 RAG 仍引用旧版本", "知识文档已修改，RAG 数小时后仍返回旧答案。你怎样设计索引新鲜度与版本切换？", ("用内容哈希和文档版本追踪解析、分块、向量化与索引状态", "更新采用新版本写入并在完整可查后原子切换，避免部分新旧混合", "删除使用 tombstone 并清理缓存、重排候选和旧索引", "监控源更新时间到可检索时间，并用版本 canary 验证"), SOURCES["rag"]),
    e(I, "sdet_flaky_tests", "sdet", "testing.automation", "medium", "CI 测试偶发失败", "一组自动化测试在本地稳定、CI 偶发失败，重跑通常通过。你如何治理而不是无限重试？", ("收集失败时间、并发度、随机种子、资源与外部依赖证据", "隔离共享状态、时间依赖、未等待异步任务和顺序耦合", "重试只用于诊断且必须保留首次失败，不能把 flaky 当通过", "建立 flaky 率、责任人和隔离时限，修复后做重复与并发验证"), SOURCES["sdet"]),
    e(I, "sdet_load_bottleneck", "sdet", "testing.performance", "medium", "压测客户端先成为瓶颈", "压测显示服务到达上限，但服务 CPU 很低、压测机 CPU 已满。如何避免得出错误容量结论？", ("同时监控发生器、网络、负载均衡和服务端资源", "校验实际到达率、连接复用、响应校验与协调遗漏", "多发生器分布式施压并用已知快接口校准工具上限", "报告吞吐必须伴随并发、延迟分布、错误率和测试环境"), SOURCES["sdet"]),
    e(I, "sdet_env_contamination", "sdet", "testing.strategy", "beginner", "共享测试环境数据互相污染", "两个测试任务并行运行时互相删除数据，导致结果不稳定。你会怎样改造测试隔离？", ("每次运行使用唯一命名空间、租户或事务数据", "测试自己创建并清理资源，不能依赖固定全局记录", "对无法隔离的外部依赖串行化并明确容量限制", "记录种子与资源标识，使失败可重放且清理可审计"), SOURCES["sdet"]),
    e(I, "network_ephemeral_ports", "cs_general", "network.core", "advanced", "客户端临时端口耗尽", "服务端健康但调用方大量 connect timeout，调用方存在大量 TIME_WAIT。如何判断是否临时端口耗尽？", ("检查连接建立率、TIME_WAIT、端口范围和 NAT/代理连接表", "确认是否未复用连接、连接池过小或主动关闭方过度建连", "优先修复 keep-alive 与池化，再评估端口范围和超时参数", "压测验证连接创建率下降且无复用错误，不能直接粗暴缩短 TIME_WAIT"), SOURCES["general"]),
    e(I, "os_disk_io", "cs_general", "os.core", "medium", "磁盘 IO 抖动拖慢数据库", "数据库 CPU 不高但查询 P99 周期性尖刺，磁盘 await 同期升高。你怎样区分缓存、刷盘和后台任务影响？", ("关联 iostat、队列深度、fsync、page cache 与数据库 checkpoint", "检查备份、日志轮转和 compaction 等周期任务", "用读取命中率和脏页比例区分随机读与集中刷盘", "错峰或限速后台任务并用相同工作集验证尾延迟"), SOURCES["general"]),

    # 26 fundamentals documents.
    e(F, "go_scheduler", "go_backend", "go.runtime", "beginner", "Go 调度器 G-P-M", "G、P、M 分别表示什么？goroutine 阻塞在系统调用时调度器怎样继续运行其他任务？", ("G 表示 goroutine，M 表示执行线程，P 持有运行 Go 代码所需资源", "P 的本地队列与全局队列共同提供可运行 G", "阻塞系统调用时 P 可与 M 分离并交给其他 M", "work stealing 改善各 P 负载不均但不保证业务公平"), SOURCES["go"]),
    e(F, "go_gc_escape", "go_backend", "go.runtime", "medium", "Go 逃逸分析与 GC 成本", "Go 中变量逃逸到堆意味着什么？为什么不能简单认为返回局部变量地址就一定慢？", ("逃逸分析决定对象可否安全放在栈上，与源码表面形式不完全等价", "堆对象增加分配与 GC 扫描成本，但编译器可内联和优化", "用编译器逃逸报告与 benchmark/pprof 验证而非凭规则猜测", "优先减少高频路径真实分配，避免为零收益牺牲可读性"), SOURCES["go"]),
    e(F, "go_interface_nil", "go_backend", "go.runtime", "medium", "Go interface 的 nil 陷阱", "为什么一个保存了 nil 指针的 interface 与 nil 比较可能为 false？怎样避免错误判断？", ("interface 包含动态类型和动态值，只有两者都为空才等于 nil", "类型信息存在而动态值为 nil 时 interface 本身非 nil", "API 尽量返回明确 nil interface，调用处按约定判断错误", "反射判断需谨慎且通常不应替代清晰的类型设计"), SOURCES["go"]),
    e(F, "java_jmm", "java_backend", "java.jvm", "medium", "Java 内存模型与 happens-before", "volatile 能保证什么，不能保证什么？请用 happens-before 解释可见性与有序性。", ("volatile 写 happens-before 后续对同一变量的读", "它保证相关写入可见并限制特定重排序", "复合读改写仍非原子，需要锁或原子类", "正确同步还包括线程启动、join 与锁释放获取规则"), SOURCES["java"]),
    e(F, "java_gc_roots", "java_backend", "java.jvm", "advanced", "JVM 可达性分析与收集器选择", "JVM 怎样从 GC Roots 判断对象存活？选择低停顿收集器时要权衡什么？", ("线程栈、静态字段、JNI 引用等可作为 GC Roots", "可达性而非引用计数决定普通对象是否存活", "低停顿收集器用并发与屏障换取 CPU、内存和复杂度", "选择应基于堆规模、分配速率、延迟目标和吞吐目标"), SOURCES["java"]),
    e(F, "java_classloading", "java_backend", "java.jvm", "beginner", "类加载与双亲委派", "Java 类加载通常经历哪些阶段？双亲委派解决了什么问题？", ("加载、验证、准备、解析、初始化具有不同职责", "父加载器优先减少核心类重复与伪造风险", "类身份同时由类名和定义它的加载器决定", "插件与容器可能有意打破委派，但必须处理隔离和依赖冲突"), SOURCES["java"]),
    e(F, "spring_proxy", "java_backend", "java.spring", "medium", "Spring 代理与自调用失效", "为什么同一个对象内部调用带事务或缓存注解的方法时，注解可能不生效？", ("常见 AOP 能力由代理拦截外部调用实现", "对象内部 this 调用绕过代理，因此拦截器没有执行", "可重构职责让调用经过代理或使用编程式边界", "还需考虑 private/final 方法与代理方式限制"), SOURCES["java"]),
    e(F, "python_gil", "python_backend", "python.runtime", "beginner", "Python GIL 与线程适用场景", "CPython 的 GIL 为什么限制 CPU 密集线程，却不意味着线程对所有任务都无用？", ("GIL 保护解释器对象状态，同一进程通常一次执行一个 Python 字节码线程", "IO 等待会释放执行机会，因此线程仍适合大量阻塞 IO", "CPU 密集任务可用多进程或释放 GIL 的原生扩展", "GIL 不替代业务数据同步，复合操作仍需正确并发设计"), SOURCES["python"]),
    e(F, "python_event_loop", "python_backend", "python.web", "medium", "Python 事件循环与协程调度", "async/await 怎样让单线程处理大量 IO？什么代码会破坏这种并发？", ("协程在 await 未就绪 IO 时主动让出控制权", "事件循环调度就绪任务而不是为每请求创建线程", "同步阻塞 IO 和长时间 CPU 计算会阻塞整个循环", "需要用异步库、执行器或独立计算服务隔离阻塞工作"), SOURCES["python"]),
    e(F, "python_memory", "python_backend", "python.runtime", "medium", "引用计数与循环垃圾回收", "CPython 为什么同时需要引用计数和循环垃圾回收？对象释放后 RSS 为什么不一定下降？", ("引用计数可及时回收大多数对象但无法独立处理引用环", "循环 GC 追踪容器对象并发现不可达环", "解释器分配器可能保留 arena 供后续复用而不归还操作系统", "定位内存需区分活对象增长、分配器保留和原生扩展泄漏"), SOURCES["python"]),
    e(F, "python_wsgi_asgi", "python_backend", "python.web", "beginner", "WSGI 与 ASGI", "WSGI 与 ASGI 的核心差异是什么？为什么长连接与高并发 IO 更适合 ASGI？", ("WSGI 主要描述同步请求响应调用接口", "ASGI 用异步事件支持 HTTP、WebSocket 和生命周期", "ASGI 不会自动把同步业务变快，阻塞代码仍需隔离", "部署时服务器、框架和中间件都必须遵循相同并发模型"), SOURCES["python"]),
    e(F, "js_event_loop", "frontend", "frontend.javascript", "beginner", "浏览器事件循环", "一次脚本中 Promise 回调、setTimeout 和同步代码的执行顺序怎样判断？", ("当前任务中的同步代码先执行到栈清空", "microtask 队列通常在当前 task 后、渲染机会前清空", "setTimeout 回调进入后续 task，不保证精确时间", "无限追加 microtask 也可能阻塞渲染与用户交互"), SOURCES["frontend"]),
    e(F, "react_reconciliation", "frontend", "frontend.react", "medium", "React reconciliation 与 key", "列表中的 key 为什么必须稳定且在兄弟节点中唯一？使用数组下标有什么风险？", ("key 帮助 reconciliation 识别节点身份与复用关系", "插入、删除或重排时下标 key 会把状态错误绑定到其他数据", "稳定业务 ID 可保留正确组件状态并减少无效重建", "key 只需在同级唯一，不会作为普通 prop 自动传入组件"), SOURCES["frontend"]),
    e(F, "browser_render", "frontend", "frontend.performance", "medium", "浏览器关键渲染路径", "从 HTML 到屏幕像素通常经过哪些阶段？哪些操作容易触发布局抖动？", ("解析构建 DOM/CSSOM，形成渲染树后布局、绘制与合成", "读取布局属性后立即写样式会造成强制同步布局", "批量读写、使用合成友好属性可减少主线程工作", "优化需用 Performance trace 验证具体瓶颈"), SOURCES["frontend"]),
    e(F, "http_cache", "frontend", "frontend.performance", "beginner", "HTTP 缓存与指纹资源", "Cache-Control、ETag 和内容指纹分别适合解决什么问题？", ("max-age 控制新鲜期，immutable 适合内容不变的指纹资源", "ETag 支持过期后的条件验证并可能返回 304", "HTML 通常短缓存，指纹静态资源可长期缓存", "发布必须让旧 HTML 引用的资源继续可用一段时间"), SOURCES["frontend"]),
    e(F, "ml_bias_variance", "ml_engineer", "ml.fundamentals", "beginner", "偏差与方差", "训练误差和验证误差的组合怎样帮助判断欠拟合与过拟合？", ("训练和验证误差都高通常提示高偏差或特征不足", "训练低而验证高通常提示高方差或分布差异", "更多数据主要帮助方差问题，提升模型容量主要帮助偏差问题", "必须先确认数据与指标正确，不能仅凭两条曲线下结论"), SOURCES["ml"]),
    e(F, "ml_regularization", "ml_engineer", "ml.fundamentals", "medium", "正则化、Dropout 与早停", "L1/L2、Dropout 和 early stopping 分别如何抑制过拟合？", ("L1 倾向稀疏参数，L2 平滑限制大权重", "Dropout 训练时随机失活，推理时使用相应缩放规则", "早停用验证集选择训练轮次，本质上也限制有效复杂度", "超参数选择不能反复污染最终测试集"), SOURCES["ml"]),
    e(F, "ml_data_leakage", "ml_engineer", "ml.evaluation", "medium", "机器学习数据泄漏", "为什么随机切分可能让时间序列或同一用户数据发生泄漏？", ("未来信息或同实体近重复样本进入验证集会虚高指标", "时间任务按时间切分，用户任务按实体分组切分", "归一化、特征选择和采样参数只在训练折拟合", "建立数据血缘与泄漏审查，保留真正未触碰的测试集"), SOURCES["ml"]),
    e(F, "ml_online_metrics", "ml_engineer", "ml.evaluation", "advanced", "离线指标与在线业务指标", "模型离线 AUC 提升为什么不保证线上业务收益？怎样设计上线实验？", ("AUC 衡量排序能力但不直接编码阈值、成本和用户反馈环", "离线分布可能与线上流量、人群或曝光机制不同", "A/B 实验设置主指标、护栏指标、样本量和停止规则", "检查新奇效应、网络效应与长期影响，不能只看短期均值"), SOURCES["ml"]),
    e(F, "rag_chunking", "ai_backend", "ai.rag", "medium", "RAG 分块与父子文档", "分块过大或过小分别会怎样影响召回和生成？父子块检索解决什么问题？", ("小块定位精确但上下文不足且容易丢失指代", "大块语义混杂、向量稀释并消耗上下文预算", "可用小块召回、父块扩展保留局部相关与完整上下文", "chunk 大小、重叠和结构解析必须在标注查询集上评测"), SOURCES["rag"]),
    e(F, "agent_injection_defense", "ai_backend", "ai.agent", "advanced", "Agent 提示注入的权限边界", "为什么转义或过滤一句“ignore previous instructions”不能独立解决 Agent 提示注入？", ("攻击可混淆、跨语言或借助间接数据表达，关键词过滤不完备", "核心防线是把模型视为不可信决策者并在工具层强制授权", "最小权限、参数 schema、资源作用域和人工确认限制损害", "敏感数据按需提供，输出再做 DLP 与审计"), SOURCES["ai"]),
    e(F, "test_pyramid", "sdet", "testing.strategy", "beginner", "测试金字塔与契约测试", "为什么不能把所有质量保证都交给端到端 UI 测试？", ("单元测试快且定位准确，适合覆盖纯逻辑与边界", "集成和契约测试验证组件接口与真实序列化语义", "少量端到端测试覆盖关键用户路径但成本高且易波动", "层级比例由风险和架构决定，不应机械追求固定数字"), SOURCES["sdet"]),
    e(F, "property_testing", "sdet", "testing.automation", "medium", "性质测试与示例测试", "性质测试相对手写示例测试有什么价值？怎样避免生成大量无意义输入？", ("性质描述对一类输入都成立的不变量而非单个答案", "生成器需满足领域约束并覆盖边界分布", "失败输入应 shrink 到最小可复现反例", "性质测试补充而非替代关键业务示例与可读回归用例"), SOURCES["sdet"]),
    e(F, "load_model", "sdet", "testing.performance", "advanced", "开放模型与封闭模型压测", "开放模型和封闭模型分别模拟什么流量？协调遗漏为什么会让延迟看起来更好？", ("封闭模型固定并发，用户完成后再发下一请求", "开放模型按到达率发送，更适合模拟外部请求流", "发生器过载若停止按计划发请求会漏掉本应经历排队的延迟", "报告需包含目标与实际到达率、并发、分位数和错误"), SOURCES["sdet"]),
    e(F, "tcp_congestion", "cs_general", "network.core", "medium", "TCP 流量控制与拥塞控制", "接收窗口和拥塞窗口分别保护谁？实际发送上限如何决定？", ("接收窗口反映接收端缓冲能力，避免压垮接收方", "拥塞窗口由发送端根据网络反馈控制，避免压垮网络", "在途数据通常受两者较小值限制", "丢包、RTT 与算法阶段共同影响吞吐，不能只看带宽"), SOURCES["general"]),
    e(F, "process_thread", "cs_general", "os.core", "beginner", "进程、线程与上下文切换", "进程和线程在资源隔离与共享方面有什么区别？上下文切换成本来自哪里？", ("进程拥有独立地址空间，线程共享进程资源但有各自栈和寄存器", "线程通信方便但共享状态需要同步且故障隔离较弱", "切换涉及调度状态、寄存器以及缓存/TLB 局部性损失", "选择并发模型应看隔离、通信、负载和运行时实现"), SOURCES["general"]),

    # 28 role-neutral coding questions: 10 beginner, 12 medium, 6 advanced.
    e(L, "two_sum", "cs_general", "algorithm.core", "beginner", "两数之和", "给定整数数组和目标值，返回和为目标值的两个不同元素下标；保证恰有一组答案。", ("单次扫描哈希表保存已见值到下标", "查询 target-current 后再写入以避免复用同一元素", "说明 O(n) 时间与 O(n) 空间", "覆盖重复值和负数"), "original://cs-interview/two-sum"),
    e(L, "valid_parentheses", "cs_general", "algorithm.core", "beginner", "有效括号", "判断只含三类括号的字符串是否正确嵌套并完全闭合。", ("左括号入栈，右括号匹配栈顶", "空栈遇右括号立即失败", "结尾栈必须为空", "O(n) 时间并覆盖空串"), "original://cs-interview/valid-parentheses"),
    e(L, "reverse_list", "cs_general", "algorithm.core", "beginner", "反转单链表", "原地反转一个单链表并返回新的头节点。", ("保存 next 后反转当前指针", "维护 previous/current 不丢失剩余链表", "返回 previous 而非 current", "覆盖空链表和单节点"), "original://cs-interview/reverse-list"),
    e(L, "binary_search", "cs_general", "algorithm.core", "beginner", "二分查找", "在升序无重复数组中查找目标值下标，不存在返回 -1。", ("维护闭区间或半开区间且规则一致", "中点计算避免整数溢出", "比较后严格缩小区间", "覆盖首尾、空数组和不存在"), "original://cs-interview/binary-search"),
    e(L, "max_subarray", "cs_general", "algorithm.core", "beginner", "最大子数组和", "返回非空连续子数组的最大元素和。", ("当前位置最优为单独开始或接续前缀", "全局最优每步更新", "不能把全负数组错误返回零", "O(n) 时间 O(1) 额外空间"), "original://cs-interview/max-subarray"),
    e(L, "tree_depth", "cs_general", "algorithm.core", "beginner", "二叉树最大深度", "计算二叉树从根到最远叶子的节点数。", ("空树深度为零", "递归为 1+左右最大值或 BFS 分层", "说明 O(n) 时间", "讨论极深树递归栈风险"), "original://cs-interview/tree-depth"),
    e(L, "queue_stacks", "cs_general", "algorithm.core", "beginner", "用两个栈实现队列", "实现 push、pop、peek、empty，并给出摊还复杂度。", ("输入栈负责写入，输出栈为空时一次性搬运", "搬运后顺序反转满足 FIFO", "每元素最多搬运一次因此摊还 O(1)", "空队列行为明确"), "original://cs-interview/queue-stacks"),
    e(L, "remove_duplicates", "cs_general", "algorithm.core", "beginner", "有序数组原地去重", "原地保留有序数组每个值的一份并返回新长度。", ("快指针扫描、慢指针指向写入位置", "只在值变化时写入", "空数组与单元素正确", "O(n) 时间 O(1) 空间"), "original://cs-interview/remove-duplicates"),
    e(L, "first_unique", "cs_general", "algorithm.core", "beginner", "第一个唯一字符", "返回字符串中第一个只出现一次字符的位置，不存在返回 -1。", ("先统计频率再按原顺序扫描", "字符集假设必须说明", "UTF-8 场景区分字节、rune 与原字节索引", "O(n) 时间"), "original://cs-interview/first-unique"),
    e(L, "merge_two_lists", "cs_general", "algorithm.core", "beginner", "合并两个有序链表", "合并两个升序链表并复用原节点返回新头。", ("哑节点简化头部处理", "每次连接较小节点并前进", "循环结束挂接剩余链表", "O(m+n) 时间 O(1) 额外空间"), "original://cs-interview/merge-two-lists"),
    e(L, "group_anagrams", "cs_general", "algorithm.core", "medium", "字母异位词分组", "把由小写字母组成的字符串按字母异位关系分组。", ("排序结果或固定长度频次数组作为键", "键必须无歧义且可哈希", "比较两种方案复杂度", "覆盖空串与重复字符串"), "original://cs-interview/group-anagrams"),
    e(L, "product_except_self", "cs_general", "algorithm.core", "medium", "除自身以外数组乘积", "不使用除法，在 O(n) 时间返回每个位置之外所有元素的乘积。", ("第一遍写入左侧前缀积", "反向维护右侧后缀积并相乘", "无需额外前后缀数组", "正确处理一个或多个零"), "original://cs-interview/product-except-self"),
    e(L, "kth_largest", "cs_general", "algorithm.core", "medium", "数组第 K 大元素", "返回无序数组第 K 大元素，不要求去重。", ("大小为 k 的最小堆或 quickselect", "明确重复元素计入排名", "堆方案 O(n log k)", "quickselect 平均 O(n) 但需处理最坏情况"), "original://cs-interview/kth-largest"),
    e(L, "level_order", "cs_general", "algorithm.core", "medium", "二叉树层序遍历", "按层返回二叉树节点值，每层一个数组。", ("队列保存当前待处理节点", "每轮先记录当前队列长度界定一层", "子节点按左右顺序入队", "O(n) 时间且空间与最大宽度相关"), "original://cs-interview/level-order"),
    e(L, "validate_bst", "cs_general", "algorithm.core", "medium", "验证二叉搜索树", "判断二叉树是否满足所有左子树值小于节点、右子树值大于节点。", ("递归传递上下界而非只比较直接孩子", "上下界使用足够宽类型或可空边界", "重复值按题意判无效", "中序严格递增也是可行解"), "original://cs-interview/validate-bst"),
    e(L, "num_islands", "cs_general", "algorithm.core", "medium", "岛屿数量", "在由陆地和水组成的网格中计算四方向连通岛屿数量。", ("遇未访问陆地时计数并 DFS/BFS 淹没整块", "边界与访问标记正确", "每格最多访问一次", "讨论递归栈和迭代队列取舍"), "original://cs-interview/number-islands"),
    e(L, "coin_change", "cs_general", "algorithm.core", "medium", "零钱兑换", "给定硬币面额和金额，返回凑成金额的最少硬币数，无法凑成返回 -1。", ("dp[x] 表示金额 x 的最优解", "从可达前驱更新并使用不可达哨兵", "完全背包允许重复使用硬币", "O(amount*coins) 时间"), "original://cs-interview/coin-change"),
    e(L, "lis", "cs_general", "algorithm.core", "medium", "最长严格递增子序列", "返回数组最长严格递增子序列长度，要求优于 O(n²)。", ("tails[i] 保存长度 i+1 子序列的最小结尾", "对每个值二分第一个大于等于它的位置", "tails 不是实际子序列但长度正确", "O(n log n) 时间"), "original://cs-interview/lis"),
    e(L, "rotated_search", "cs_general", "algorithm.core", "medium", "旋转有序数组查找", "在无重复的旋转升序数组中以 O(log n) 查找目标。", ("每轮至少一半区间有序", "判断目标是否落在有序半边", "边界比较保持一致并严格缩小", "覆盖未旋转和旋转点两侧"), "original://cs-interview/rotated-search"),
    e(L, "trie", "cs_general", "algorithm.core", "medium", "前缀树", "实现插入、完整单词查找和前缀查找。", ("节点维护子边与单词结束标记", "完整查找必须检查结束标记", "复杂度与字符串长度成正比", "说明字符集对数组或哈希子节点的影响"), "original://cs-interview/trie"),
    e(L, "min_stack", "cs_general", "algorithm.core", "medium", "最小栈", "实现 push、pop、top、getMin，所有操作 O(1)。", ("辅助栈同步保存当前位置最小值", "重复最小值需要重复记录或计数", "pop 时两个栈状态同步", "明确空栈操作契约"), "original://cs-interview/min-stack"),
    e(L, "linked_cycle_entry", "cs_general", "algorithm.core", "medium", "链表环入口", "若单链表有环返回入口节点，否则返回空，要求 O(1) 空间。", ("快慢指针先判断并在环内相遇", "相遇后一个指针回到头部并同速前进", "再次相遇点为入口", "解释基于头到入口与环长度的距离关系"), "original://cs-interview/cycle-entry"),
    e(L, "median_stream", "cs_general", "algorithm.core", "advanced", "数据流中位数", "支持持续插入整数并随时返回当前中位数。", ("最大堆保存较小一半，最小堆保存较大一半", "维护堆大小差不超过一", "中位数由堆顶一个或两个值计算", "插入 O(log n)、查询 O(1)"), "original://cs-interview/median-stream"),
    e(L, "lfu_cache", "cs_general", "algorithm.core", "advanced", "LFU 缓存", "实现固定容量 LFU 缓存，频率相同时淘汰最久未使用项，get/put 平均 O(1)。", ("键映射到值、频率和链表节点", "频率映射到维护 LRU 顺序的双向链表", "维护当前最小频率并在提升/淘汰时更新", "容量为零、更新已有键和频率并列正确"), "original://cs-interview/lfu-cache"),
    e(L, "word_ladder", "cs_general", "algorithm.core", "advanced", "单词接龙", "每次只改一个字符且中间词必须在字典中，返回从起点到终点的最短序列长度。", ("将状态视为图并用 BFS 求最短路", "生成邻居时避免重复访问", "可用通配模式或双向 BFS 降低搜索", "终点不在字典和起终相同边界明确"), "original://cs-interview/word-ladder"),
    e(L, "min_window", "cs_general", "algorithm.core", "advanced", "最小覆盖子串", "返回字符串中覆盖目标字符串全部字符及频次的最短窗口。", ("右指针扩张并更新窗口计数", "满足全部需求后左指针收缩并更新最优", "用满足种类数避免每次扫描全部字符", "覆盖重复字符与不存在答案"), "original://cs-interview/min-window"),
    e(L, "merge_k_lists", "cs_general", "algorithm.core", "advanced", "合并 K 个有序链表", "合并 K 个升序链表，要求优于每次线性寻找最小头节点。", ("最小堆保存每条非空链表当前头", "弹出后将该节点的 next 入堆", "复杂度 O(N log k)", "也可分治两两合并并说明等价复杂度"), "original://cs-interview/merge-k-lists"),
    e(L, "trap_rain", "cs_general", "algorithm.core", "advanced", "接雨水", "给定柱高数组，计算下雨后能接的总水量，要求 O(1) 额外空间。", ("双指针维护左右已见最大高度", "较低一侧的最大值决定该侧当前位置水量", "每步移动可确定的一侧并累加非负差", "O(n) 时间 O(1) 空间且覆盖单调数组"), "original://cs-interview/trap-rain"),
]


def render(entry: Entry) -> str:
    heading = "场景题" if entry.dataset == I else "算法题" if entry.dataset == L else "基础题"
    section = "评分点" if entry.dataset != F else "参考要点"
    followups = (
        ("如果第一步没有发现异常，你会怎样继续缩小范围？", "如何设计量化验证和安全回滚标准？")
        if entry.dataset == I
        else ("如何证明算法正确并给出复杂度？", "哪些边界输入最容易出错？")
        if entry.dataset == L
        else ("这个机制最常见的误区是什么？", "在什么边界下应该选择另一种方案？")
    )
    points = "\n".join(f"- {point}" for point in entry.points)
    probes = "\n".join(f"{index}. {question}" for index, question in enumerate(followups, 1))
    return f"# {heading}：{entry.title}\n\n## 问题\n\n{entry.question}\n\n## {section}\n\n{points}\n\n## 追问\n\n{probes}\n"


def validate() -> None:
    assert len(ENTRIES) == 81, len(ENTRIES)
    assert Counter(item.dataset for item in ENTRIES) == {I: 27, L: 28, F: 26}
    ids = [f"scale-{item.dataset[:4]}-{item.slug}-001" for item in ENTRIES]
    assert len(ids) == len(set(ids))
    for item in ENTRIES:
        assert item.role in VALID_ROLE_TOPICS
        assert item.topic in VALID_ROLE_TOPICS[item.role]
        assert item.difficulty in {"beginner", "medium", "advanced"}
        assert len(item.question) >= 15
        assert len(item.points) >= 4 and all(len(point) >= 5 for point in item.points)


def main() -> None:
    validate()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    non_generated = []
    for spec in manifest["datasets"].values():
        retained = [doc for doc in spec["documents"] if "/generated/" not in doc["path"]]
        non_generated.extend(retained)
        spec["documents"] = retained
    assert len(non_generated) == 19, f"Expected 19 hand-written documents, got {len(non_generated)}"

    for item in ENTRIES:
        relative = Path("docs") / item.dataset / "generated" / f"{item.slug}.md"
        destination = ROOT / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render(item), encoding="utf-8", newline="\n")
        content_type = item.dataset
        question_id = f"scale-{item.dataset[:4]}-{item.slug}-001"
        manifest["datasets"][item.dataset]["documents"].append(
            {
                "path": relative.as_posix(),
                "metadata": {
                    "content_type": content_type,
                    "role": item.role,
                    "topic": item.topic,
                    "difficulty": item.difficulty,
                    "question_id": question_id,
                    "source": item.source,
                    "source_date": SOURCE_DATE,
                    "quality_score": 0.94,
                    "verified": True,
                    "license": "CC-BY-4.0-original-summary",
                },
            }
        )

    counts = {key: len(spec["documents"]) for key, spec in manifest["datasets"].items()}
    assert counts == {I: 34, L: 33, F: 33}, counts
    manifest["version"] = 2
    manifest["name"] = "CS Interview 100-document public-source evaluation corpus"
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    role_counts = Counter(
        doc["metadata"]["role"]
        for spec in manifest["datasets"].values()
        for doc in spec["documents"]
    )
    difficulty_counts = Counter(
        doc["metadata"]["difficulty"]
        for spec in manifest["datasets"].values()
        for doc in spec["documents"]
    )
    print(json.dumps({"documents": sum(counts.values()), "datasets": counts, "roles": role_counts, "difficulties": difficulty_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
