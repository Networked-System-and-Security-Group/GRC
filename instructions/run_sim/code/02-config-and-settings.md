# 配置系统：config.txt → Settings/模块参数

## config.txt 的来源

`run.py` 通过 `config_template` 生成 `mix/output/[id]-.../config.txt`。

AI 新增参数时的黄金路径：
- `run.py` 写入
- `scratch/remote.cc` 解析
- 传递到：`Settings` 或具体对象

## `Settings` 里与实验高度相关的内容

- `Settings::wan_cc_mode`：WAN 模式枚举（`NONE/WAN_OPT/WITH_ECN`）
- `Settings::wan_routing`：WAN 路由表（从某个 switch 到某个 dst_as 的 next-hop dev index 列表）
- `Settings::nodeInfos`：每个节点的类型/AS/ID/IP
- `Settings::if2id` / `Settings::nbr2if`：接口与邻居信息（日志里大量用它们映射“port→对端节点”）

## 为什么 `OUTPUT_DIR_PATH` 很关键

`Settings::initialize_log()` 会用 `logfile::output_dir` 打开所有输出文件。
因此：
- 要让新增日志落盘，必须确保 `OUTPUT_DIR_PATH` 解析正确

