# Rollback Guide

## 最小回退

如果你只想关闭这次 FEC 功能，而不回退其它代码：

1. 在 `config.txt` 中将 `FEC_PARITY_PKTS` 设为 `0`
2. 保留代码不动

这样 `FecEnable` 不会打开，运行时会回到原始非 FEC 行为。

## 代码级回退顺序

如果你要逐步回退代码，建议按下面顺序：

1. 回退 `scratch/remote.cc`
2. 回退 `src/applications/model/rdma-client.h`
3. 回退 `src/applications/model/rdma-client.cc`
4. 回退 `src/point-to-point/model/rdma-driver.h`
5. 回退 `src/point-to-point/model/rdma-driver.cc`
6. 回退 `src/point-to-point/model/settings.h`
7. 回退 `src/network/model/flow-id-num-tag.h`
8. 回退 `src/network/model/flow-id-num-tag.cc`
9. 回退 `src/point-to-point/model/rdma-queue-pair.h`
10. 回退 `src/point-to-point/model/rdma-queue-pair.cc`
11. 回退 `src/point-to-point/model/rdma-hw.h`
12. 回退 `src/point-to-point/model/rdma-hw.cc`
13. 回退 `src/point-to-point/model/qbb-net-device.cc`
14. 回退 `run.py`

## 回退时要注意

- `flow-id-num-tag`、`rdma-queue-pair`、`rdma-hw` 三者是联动的，不能只回其中一个
- `remote.cc` 和 `rdma-client` / `rdma-driver` 的每流 `fec_n` 传递链也是联动的
- 如果只删 `FecEnable` 但保留 FEC tag 字段，通常仍可编译，但会留下死代码
