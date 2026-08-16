# FEC（每组先发 `n` 个冗余包，再发 `m` 个正常包）改造计划

## 本版定案

这版计划先按下面的目标收敛，不改具体代码，只把设计说清楚：

- 每个 FEC 组固定由两段组成
  - 先发送 `n` 个冗余包
  - 再发送 `m` 个正常包
- ACK 频率和 `m` 保持一致
  - 一组正常包对应一次 ACK 机会
  - 不按 `m+n` 回 ACK
- 冗余包和正常包的 `seq` 分开
  - 正常包继续使用现有 RDMA 的数据字节序号
  - 冗余包使用独立的冗余序号空间
  - 冗余包不能推进、占用、污染正常包的累计 `seq`
- `config` 里提供一个默认 `n`
- 每条流在输入/建流时先绑定这个默认 `n`
- 同一时刻不同流可以使用不同的 `n`

## 核心语义

### 1. 发送顺序

以一组 `m=40, n=10` 为例，本版目标是：

1. 先发 10 个冗余包
2. 再发 40 个正常包
3. 这 40 个正常包对应当前 ACK 频率
4. 接收端对这一组最多回一次 ACK

这里之所以允许“冗余先发”，前提是第一版采用的是**理想化 FEC 仿真语义**，不是做真实编码：

- 不真正计算 parity payload
- 冗余包只是“占带宽、占在途、参与组恢复计数”的逻辑包
- 因此发送顺序不再受“必须先拿到数据才能编码”的真实编码约束

### 2. ACK 语义

ACK 的单位改成“正常包组”，不是“所有包组”：

- `m` = 一组正常包数量
- `n` = 这一组前置冗余包数量
- ACK 边界只跟 `m` 绑定

换句话说：

- 正常包组大小是 `m`
- 实际发送批次大小是 `n + m`
- 但 ACK 频率只看 `m`

因此，原文档里“ACK 频率改成按 `m+n` 生效”这一点，这版要改掉，改成：

- ACK 频率按 `m` 生效
- `n` 只影响冗余强度，不改变正常数据的累计 ACK 步长

### 3. 恢复条件

对组 `g`：

- 该组有 `m` 个正常包槽位
- 该组有 `n` 个冗余包槽位
- 接收端按组统计“有效到达数”

当某组满足下面条件时，认为该组可恢复：

- `group_received_total >= m`

但“可恢复”与“实际发 ACK”分开：

- `recoverable`：组内已有足够多的包，理论上能恢复该组正常数据
- `ack_emitted`：该组对应的 ACK 已经发过

这样可以把“恢复判定”和“ACK 发射时机”分离，避免后续实现时把两个概念混在一起。

补充一条实现约束：

- 只要某个 FEC 组已经 `recoverable`，后续属于该组的 `data` 包就不应再触发普通 `seq > expected` 的 NACK 逻辑
- 这类包应直接走 FEC ACK 推进语义，避免“repair 已足够但 data 仍按缺口误发 NACK”

## 序号设计

这是本次计划里最关键的改动。

### 1. 正常包 `data_seq`

正常包继续使用现有 RDMA 的数据字节序号：

- 单调递增
- 继续作为累计 ACK / NACK 的唯一基准
- 继续表示“原始应用数据已经确认到哪里”

也就是说：

- 正常包消耗 `data_seq`
- ACK 返回的 `seq` 仍然是正常数据的累计字节边界

### 2. 冗余包 `repair_seq`

冗余包不进入正常数据序号空间，而是使用独立的冗余序号空间。

我建议第一版不要强行让它复用现有累计 `seq` 语义，而是直接定义成：

- 主键：`(fec_group_id, repair_idx)`
- 可选展开值：`repair_seq = (fec_group_id << 16) | repair_idx`

其中：

- `fec_group_id`：该流内第几个 FEC 组
- `repair_idx`：该组内第几个冗余包，范围 `[0, n-1]`

这样做的好处是：

- 冗余包天然不会与正常包 `data_seq` 冲突
- 不需要让冗余包去“假装”自己是某段数据字节
- 接收端按组恢复时直接用组号和组内索引即可

### 3. ACK 只认 `data_seq`

本版明确规定：

- 冗余包的 `repair_seq` 不参与累计 ACK
- 冗余包的 `repair_seq` 不推进 `ReceiverNextExpectedSeq`
- 冗余包的 `repair_seq` 不作为 NACK 的字节缺口判断依据

ACK 中回的还是：

- “这一组正常数据末尾的累计字节边界”

例如 `m=40`、`payload=1000B`：

- 每组 ACK 步长仍然是 `40000`
- 冗余包数量 `n` 再大，也不能让 ACK 步长变成 `50000`、`60000`

### 4. 兼容现有包头的落地方式

现有代码路径里，正常收发逻辑大量依赖 `udp.seq` / ACK `seq`。

因此第一版计划是：

- 正常包：继续走现有 `SeqTsHeader` / `udp.seq`
- 冗余包：真实“组身份”和“冗余序号”放进 `FlowIDNUMTag`
- 接收端在 FEC 模式下看到 `fec_pkt_role = repair` 时，走单独的 FEC 路径，不让它进入正常累计 `seq` 逻辑
- 接收端在 FEC 模式下如果某组已经 `recoverable`，则不再对该组 `data` 包执行普通 NACK 判定

这意味着第一版不追求“交换机也理解冗余序号”，而是先在 host RDMA 栈内把语义做对。

## `m`、ACK 频率、配置项的关系

### 1. `m` 不再单独漂移

这版不建议把 `m` 和 ACK 频率做成两个独立旋钮，否则后面一定会出现不一致。

建议改成：

- ACK 频率是 `m` 的唯一来源
- `m` 始终等于“每若干个正常包回一次 ACK”里的那个数量

对应到当前仓库现状：

- 当前 `PACKET_PAYLOAD_SIZE = 1000`
- 当前 `L2_ACK_INTERVAL = 40000`
- 所以默认可解释为 `m = 40`

因此第一版可以先这样约定：

- `m = L2_ACK_INTERVAL / PACKET_PAYLOAD_SIZE`

如果以后要支持更明确的包级配置，可以再补一个可读性更强的字段，例如：

- `FEC_ACK_GROUP_PKTS`

但它和 `L2_ACK_INTERVAL` 不能同时各自生效，必须有唯一真源。

### 2. `n` 是“config 默认值 + per-flow 绑定”模式

这版要改成：

- `config` 可以有一个默认 `n`
- 但运行中的 `n` 不能只存在 `RdmaHw` 的全局单一变量里
- 真正参与发送的是每个 flow / QP 自己绑定的 `n`

也就是说：

- flow A、flow B 在当前方案下都先继承 config 里的同一个默认 `n`
- 两条流共存在同一个 host 上时，`RdmaHw` 不能只存一个全局运行时 `n`

推荐落点：

- `Settings::FlowInput` 增加 `fec_n`
- `ReadFlowInput()` 读取普通 5 列 flow 行，并把 config 默认 `n` 绑定到该 flow
- 建流时经 `RdmaClient` / `RdmaDriver` 传入 `RdmaHw::AddQueuePair(...)`
- `RdmaQueuePair` 保存本流的 `fec_n`

### 3. 运行时修改 `n` 改为“按流修改”

既然 `n` 是 per-flow，运行时修改也必须改成 per-flow 语义：

- 允许修改某一条流后续新组使用的 `n`
- 不允许用一个全局开关同时覆盖所有流
- 已经创建并已发出部分包的组，继续使用创建该组时快照下来的 `n_snapshot`

原因：

- 否则运行时无法安全地只修改某一条流，而不影响同 host 上的其他流

## 推荐的元数据字段

第一版继续优先扩展 `FlowIDNUMTag`，而不是立刻改真实报文头。

建议新增这些字段：

- `fec_enabled`
- `fec_group_id`
- `fec_pkt_role`
  - `repair`
  - `data`
- `fec_group_m`
- `fec_group_n_snapshot`
- `fec_group_data_start_seq`
- `fec_data_idx`
  - 正常包在组内的索引，范围 `[0, m-1]`
- `fec_repair_idx`
  - 冗余包在组内的索引，范围 `[0, n-1]`
- `fec_tx_ordinal`
  - 该包在“先冗余后正常”的整组发送序列里的顺序，范围 `[0, n+m-1]`

其中最重要的是：

- `fec_group_id`
- `fec_pkt_role`
- `fec_repair_idx`
- `fec_data_idx`
- `fec_group_data_start_seq`

## 计划修改的文件

### 1. `scratch/remote.cc`

职责：

- 解析 `config.txt`
- 计算/校验 `m`
- 读取 config 默认 `n`
- 在建流时下发到 `RdmaHw`

计划修改点：

- 保留 `L2_ACK_INTERVAL`
- 在 FEC 模式下把它解释为“正常数据 ACK 步长”
- 由 `L2_ACK_INTERVAL / PACKET_PAYLOAD_SIZE` 推导 `m`
- 在 config 主体里增加默认 `n`，例如 `FEC_PARITY_PKTS`
- `remote.cc::ReadFlowInput()` 保持当前 5 列 flow 文件格式不变，并把默认 `n` 绑定给该 flow
- 在 `ScheduleFlowInputs()` 建流时，把该 flow 已绑定好的 `n` 传入 `RdmaHw`

这一点和原文档不同：

- 不再把 `L2_ACK_INTERVAL` 改造成 `m+n`
- 而是把它固定解释成 `m`

### 2. `run.py`

职责：

- 生成实验用 `config.txt`

计划修改点：

- `config_template` 里保留一个默认 `FEC_PARITY_PKTS`
- `L2_ACK_INTERVAL` 继续决定 `m`
- flow 文件格式不变，继续保持现有 5 列

如果想保留兼容模式，可以允许：

- `--fec-n`

它的语义改成：

- 作为 config / flow 生成时的默认 `n`
- 不是运行时唯一全局 `n`

### 3. `src/point-to-point/model/rdma-hw.h`

职责：

- `RdmaHw` 的核心状态与接口定义

计划修改点：

- 新增 FEC 开关
- 不把“运行中生效的 `n`”做成全局唯一变量
- 改为支持每个 QP/flow 自己持有已经绑定好的 `n`
- 如需运行时修改，也应是“按 flow 修改”的接口
- 新增“按组发送、按组接收、组快照”的状态定义

建议的成员方向：

- `m_fecEnabled`
- 发送/接收侧都保存 `group_id`
- 每个 QP 保存本流 `fec_n`
- 每个组保存创建时的 `m_snapshot` / `n_snapshot`

### 4. `src/point-to-point/model/rdma-hw.cc`

这是主改造文件。

#### 4.1 发送端 `GetNxtPacket(...)`

计划改造为：

- 先基于当前 ACK 频率确定本组 `m`
- 创建本组数据字节范围
- 先发送该 flow 当前组自己的 `n_snapshot` 个 `repair` 包
- 再发送 `m_snapshot` 个 `data` 包

需要额外强调：

- 冗余包占带宽、占在途
- 但不占正常数据字节序号
- 正常数据总量 `m_size` 不因为冗余包而膨胀

#### 4.2 接收端 `ReceiveUdp(...)` / `ReceiverCheckSeq(...)`

计划改造为双路径：

- `data` 包走“正常数据 + FEC 组辅助统计”路径
- `repair` 包走“只更新 FEC 组状态、不推进正常累计 seq”路径

接收端按组维护：

- 该组收到了多少个 `repair`
- 该组收到了多少个 `data`
- 总有效到达数
- 是否已 `recoverable`
- 是否已发过组 ACK

#### 4.3 ACK/NACK 条件

这版计划里的目标是：

- 每组最多回一次 ACK
- ACK 的累计值只按正常数据边界推进
- 冗余包不单独触发 ACK 边界变化

NACK 逻辑要延后：

- 不能因为某个正常包缺失就立刻按旧逻辑认定 gap
- 要先看该组是否已可恢复

### 5. `src/point-to-point/model/rdma-queue-pair.h`
### 6. `src/point-to-point/model/rdma-queue-pair.cc`

职责：

- 保存每个 flow 的发送侧 / 接收侧 FEC 状态

计划修改点：

- 发送侧增加“当前组描述符”
- 接收侧增加“按组恢复表”
- 每个组都保存自己的 `m_snapshot` / `n_snapshot`

### 7. `src/network/model/flow-id-num-tag.h`
### 8. `src/network/model/flow-id-num-tag.cc`

职责：

- 承载 FEC 元数据

计划修改点：

- 从当前的 `flow_id + flow_size + ack_req`
- 扩展到能携带组号、包角色、组内索引、组快照等信息

## 暂时不动的文件

第一版仍然不准备先动这些：

### `src/point-to-point/model/switch-node.cc`
### `src/point-to-point/model/wan-routing.cc`
### `src/network/utils/custom-header.*`
### `src/internet/model/seq-ts-header.*`
### `src/point-to-point/model/qbb-header.*`

原因：

- 交换机/WAN 转发仍然主要看原有五元组和 ACK `seq`
- FEC 组信息先放 `FlowIDNUMTag`
- 先把 host RDMA 栈语义做对，再考虑是否要把 FEC 元数据变成真实报文头

## 已明确的边界

### 1. 尾组不足 `m`

例如 `m=40`，尾组只剩 17 个正常包。

这版建议：

- 尾组使用 `tail_m`
- ACK 仍按该尾组真实正常包边界确认
- `n` 默认仍沿用当前配置值

即：

- 正常组是 `(m, n)`
- 尾组是 `(tail_m, n)`

### 2. 运行时修改 `n`

只允许按流影响新组：

- 某条流旧组保持 `n_snapshot`
- 该流新组读取该流当前绑定的 `n`
- 其他流不受影响

### 3. ACK 频率不跟着 `n` 变化

这版明确不做：

- `n` 变化后自动改变 ACK 步长

而是保持：

- ACK 步长只跟 `m` 一致

## 风险点

### 1. 现有实现是纯累计字节 `seq` 模型

现在要引入“正常数据序号空间”和“冗余序号空间”两套语义，发送/接收状态都会变复杂。

### 2. 冗余先发会改变现有 ACK 观感

虽然 ACK 仍按正常数据边界推进，但包到达顺序会变成：

- 先看到一批不推进正常 `seq` 的 `repair`
- 再看到推进正常 `seq` 的 `data`

这要求接收端显式区分两类包，不能再把所有 UDP 数据包都默认丢进同一套 `ReceiverCheckSeq(...)` 逻辑。

### 3. 运行时改 `n` 必须做组级快照

否则接收端无法判断某条流一个已经在途的组到底应该期待几个冗余包。

## 实施顺序

1. 先改计划文档并固定语义
2. 扩展 flow 输入链路，让每条流都能先绑定默认 `n`
3. 在 `remote.cc` 内把 `m` 明确绑定到 ACK 频率
4. 扩展 `FlowIDNUMTag`
5. 改发送端，支持“先本流 `n` 个 repair，再 `m` 个 data”
6. 改接收端，支持双序号空间和按组恢复
7. 最后再收敛 ACK/NACK/timeout 边界

## 这版文档最终结论

这版计划固定为：

- 发送顺序：先 `n` 个冗余包，再 `m` 个正常包
- ACK 频率：和 `m` 一致，不和 `m+n` 一致
- 序号设计：正常包 `data_seq` 与冗余包 `repair_seq` 分离
- 配置方式：`m` 由 ACK 频率推导，`config` 里给默认 `n`，每条流在建流时绑定这个 `n`
- 运行时修改：只允许按流修改 `n`，且只影响该流的新组

这比原文档更接近你现在要的目标，也避免了后续把 `m`、`n`、ACK 频率、累计 `seq` 四件事缠在一起。
