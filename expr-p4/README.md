# expr-p4 — 实验 / 观测版目录

本目录存放 GSCC P4 的**实验与观测**相关产物（区别于 `P4/` 的“可用正式版”）。

```
expr-p4/
├── bugs.md                 # 全过程踩坑记录（时间/表现/解决/出处）
└── ack/                    # ACK 聚合 + PSN 匹配观测实验
    ├── README.md
    ├── experiment.md       # 成功实验记录（原始命令+输出+结果+解读）
    ├── multi-bucket/       # 观测版 P4(a)：多桶（256 桶 × 256 槽）
    │   ├── data-plane/     #   gscc.p4 / header.p4 / util.p4
    │   └── control-plane/  #   ctrl.c / headers.h / switch_config.h / Makefile
    └── single-bucket/      # 观测版 P4(b)：单桶（归并成 1 个桶，psn[15:0]）
        ├── data-plane/
        └── control-plane/
```

> `P4/` 分支（P4-fix）是“可用正式版”（论文算法 + 无任何观测表）；本 `expr-p4/` 是“带观测、用于实验验证”的版本，仅供实验，不作为正式交付。
