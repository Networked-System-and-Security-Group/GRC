# 4) 具体代码部分：关键类与交互流程（代码地图）

本目录按“数据如何从输入文件进入仿真、在交换机/路由里被处理、再产生日志/结果”的路径组织。

## 目录

- 仿真入口与主流程：见 [01-simulation-entry.md](01-simulation-entry.md)
- 配置系统（config.txt → C++ 参数）：见 [02-config-and-settings.md](02-config-and-settings.md)
- WAN 侧 GSCC/路由逻辑：见 [03-wan-routing.md](03-wan-routing.md)
- 交换机转发/拥塞点：见 [04-switch-pipeline.md](04-switch-pipeline.md)
- 日志产出点索引：见 [05-logging-index.md](05-logging-index.md)
