This folder packages the RDMA flow files used by the paper-scan style experiments we checked.

Files

- `w-dynamic-150-0-v1.txt`
- `w-dynamic-150-60-v1.txt`
- `w-dynamic-150-120-v1.txt`
- `w-dynamic-150-180-v1.txt`
- `m-dynamic-70-150-0-v1.txt`
- `m-dynamic-70-150-60-v1.txt`
- `m-dynamic-70-150-120-v1.txt`
- `m-dynamic-70-150-180-v1.txt`

Experiment mapping

<!--- `websearch`
  - `111,112,321` -> `w-dynamic-150-0-v1.txt`
  - `117,118,322` -> `w-dynamic-150-60-v1.txt`
  - `123,124,323` -> `w-dynamic-150-120-v1.txt`
  - `129,130,324` -> `w-dynamic-150-180-v1.txt`
- `webmining`
  - `416,417,418` -> `m-dynamic-70-150-0-v1.txt`
  - `422,423,424` -> `m-dynamic-70-150-60-v1.txt`
  - `428,429,430` -> `m-dynamic-70-150-120-v1.txt`
  - `434,435,436` -> `m-dynamic-70-150-180-v1.txt`-->

Notes

- These are RDMA flow files only. TCP mixed-traffic files are not included here.
- When we compared `FLOW_FILE` against `flow_output`, the RDMA entries matched run-time output for the checked experiments.
- `w-dynamic-150-120-v1.txt` contains one entry with `size_bytes = 0`. The simulator clamps it to `1` byte at load time.
