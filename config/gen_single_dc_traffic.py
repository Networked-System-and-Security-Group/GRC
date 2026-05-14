import argparse
import json
import os.path as op

from large_traffic_gen import generate_flows


def main():
    parser = argparse.ArgumentParser(description="Generate single-DC traffic by reusing large_traffic_gen helpers")
    parser.add_argument("--as-id", type=int, required=True, help="Target AS id")
    parser.add_argument("--duration", type=float, default=0.03, help="Traffic duration in seconds")
    parser.add_argument("--intra-load", type=float, default=50.0, help="Per-host offered load in Gbps")
    parser.add_argument("--cdf", type=str, default="WebSearch", help="CDF stem under traffic_gen/")
    parser.add_argument("--topo", type=str, default="cernet_topo.txt", help="Topology JSON file under config/")
    parser.add_argument("--output", type=str, required=True, help="Output flow filename under config/")
    args = parser.parse_args()

    topo_path = op.join(op.dirname(__file__), args.topo)
    with open(topo_path, "r") as f:
        topo = json.load(f)

    as_topologies = topo["as_topologies"]
    if args.as_id < 0 or args.as_id >= len(as_topologies):
        raise ValueError(f"AS id {args.as_id} is out of range; total AS num = {len(as_topologies)}")

    hosts = as_topologies[args.as_id]["hosts"]
    cdf_path = op.join(op.dirname(__file__), "../traffic_gen", args.cdf + ".txt")
    flows = generate_flows(hosts, hosts, cdf_path, f"{args.intra_load}G", args.duration, 2.0)

    output_path = op.join(op.dirname(__file__), args.output)
    with open(output_path, "w") as ofile:
        ofile.write(f"{len(flows)}\n")
        for flow in flows:
            ofile.write(str(flow) + "\n")

    print(f"Single-DC flow count: {len(flows)}, Saved to: {output_path}")


if __name__ == "__main__":
    main()
