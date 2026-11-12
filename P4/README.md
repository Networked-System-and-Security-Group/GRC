# GSCC on Tofino2

- [dataplane/](dataplane/): the GSCC data plane with exact PSN matching.
- [controlplane/](controlplane/): the controller for that data plane.
- [experiments/](experiments/): the separately instrumented ACK/PSN experiment and its runner. Its P4 program and controller must be built and used together.

## Build the algorithm implementation

Use a Tofino2 SDE with the T2NA compiler (the original setup used SDE 9.7.1).
Copy `dataplane/testbed.p4.example` to `dataplane/testbed.p4` and set the two IPv4 addresses and Tofino device ports before compiling. The example uses documentation addresses. The local header is ignored by Git.

```sh
cd dataplane
bf-p4c --std p4-16 --target tofino2 --arch t2na \
  --bf-rt-schema build/bf-rt.json -o build gscc.p4
cd ..
make -C controlplane SDE_INSTALL="$SDE_INSTALL"
```

Prepare a switchd configuration for your board and the generated program. Set `GSCC_CONF`, `SDE_INSTALL`, `GSCC_PORTS` (comma-separated device ports), and the runtime library path before starting `controlplane/ctrl`. `GSCC_PROG` selects the program name if it differs from `gscc`; `GSCC_MIRROR_PORT` sets the CNP mirror egress device port. The controller configures the listed ports for 100 Gbps with RS-FEC.
