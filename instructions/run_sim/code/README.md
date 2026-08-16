# 4) 具体代码部分：关键类与交互流程（代码地图）

本目录按“数据如何从输入文件进入仿真、在交换机/路由里被处理、再产生日志/结果”的路径组织。

## 目录

- 仿真入口与主流程：见 [01-simulation-entry.md](01-simulation-entry.md)
- 配置系统（config.txt → C++ 参数）：见 [02-config-and-settings.md](02-config-and-settings.md)
- WAN 侧 GSCC/路由逻辑：见 [03-wan-routing.md](03-wan-routing.md)
- 交换机转发/拥塞点：见 [04-switch-pipeline.md](04-switch-pipeline.md)
- 日志产出点索引：见 [05-logging-index.md](05-logging-index.md)
- WAN switch RED 丢包：见 [06-wan-switch-red-drop.md](06-wan-switch-red-drop.md)
- WAN RED 实施与回退：见 [07-wan-red-implementation-and-rollback.md](07-wan-red-implementation-and-rollback.md)
- WAN dynamic 5000 流对比模板：见 [09-wan-dynamic-fct-compare-5000.md](09-wan-dynamic-fct-compare-5000.md)
- WAN RED/FEC 参数敏感性扫参模板：见 [10-wan-red-fec-sensitivity-sweep.md](10-wan-red-fec-sensitivity-sweep.md)
- WAN RED/FEC 扫参修改记录：见 [11-wan-red-fec-sweep-change-log.md](11-wan-red-fec-sweep-change-log.md)
- WAN RED/FEC 15 组联调模板：见 [12-wan-red-fec-15-joint-sweep.md](12-wan-red-fec-15-joint-sweep.md)
- WAN RED/FEC 60 组宽间隔联调模板：见 [13-wan-red-fec-60-wide-sweep.md](13-wan-red-fec-60-wide-sweep.md)
- TCP/RDMA 共存、队列与交换机 Buffer：见 [14-tcp-rdma-coexist-buffer-analysis.md](14-tcp-rdma-coexist-buffer-analysis.md)
- TCP/RDMA 共存实现审计、错误与修复顺序：见 [15-tcp-rdma-coexist-implementation-audit.md](15-tcp-rdma-coexist-implementation-audit.md)
- `w-tcp-300` WAN TCP offered load 的计算：见 [16-w-tcp-300-wan-rate-calculation.md](16-w-tcp-300-wan-rate-calculation.md)
