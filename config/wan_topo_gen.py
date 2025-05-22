import json
import os.path as op

next_node_id = 0

def get_next_id():
    global next_node_id
    cur = next_node_id
    next_node_id += 1
    return cur

def generate_fattree_topology(k):
    """
    生成经典 fat-tree 拓扑（每个 DC 内部），节点生成顺序为：
      1. 所有 host
      2. 所有 edge 交换机
      3. 所有 aggregation 交换机
      4. 所有 core 交换机
      5. 最后生成 DCI 交换机
    fat-tree 参数：
      - pods = k
      - 每个 pod 内有 k/2 个 edge 交换机和 k/2 个 aggregation 交换机
      - 每个 edge 交换机挂接 k/2 个 host
      - 核心交换机数 = (k//2)^2
    """
    bw = "100Gbps"
    delay = '1000ns'
    loss = float(0)

    pods = k
    num_edge_per_pod = k // 2
    num_agg_per_pod = k // 2
    hosts_per_edge = k // 2
    num_core = (k // 2) ** 2

    # 1. 生成所有 host（按照 pod 和 edge 顺序）
    host_map = {}
    hosts = []
    for p in range(pods):
        for e in range(num_edge_per_pod):
            host_ids = []
            for _ in range(hosts_per_edge):
                host_id = get_next_id()
                host_ids.append(host_id)
                hosts.append(host_id)
            host_map[(p, e)] = host_ids

    # 2. 生成所有 edge 交换机（按照 pod 和 edge 顺序）
    edge_map = {}
    edge_switches = []
    for p in range(pods):
        for e in range(num_edge_per_pod):
            edge_id = get_next_id()
            edge_map[(p, e)] = edge_id
            edge_switches.append(edge_id)

    # 3. 生成所有 aggregation 交换机（按照 pod 和 agg 顺序）
    agg_map = {}
    agg_switches = []
    for p in range(pods):
        for a in range(num_agg_per_pod):
            agg_id = get_next_id()
            agg_map[(p, a)] = agg_id
            agg_switches.append(agg_id)

    # 4. 生成所有 core 交换机（顺序生成）
    core_switches = []
    for _ in range(num_core):
        core_id = get_next_id()
        core_switches.append(core_id)

    # 5. 生成 DCI 交换机（最后生成）
    dci_switch = get_next_id()

    # 生成链路列表，所有链路均采用 bw="100Gbps", delay=1000, loss=0
    links = []

    # (a) 每个 edge 交换机与其挂接的 host 之间建立链路
    for p in range(pods):
        for e in range(num_edge_per_pod):
            edge_id = edge_map[(p, e)]
            for host_id in host_map[(p, e)]:
                links.append((edge_id, host_id, bw, delay, loss))

    # (b) 同一 pod 内，每个 edge 交换机与所有 aggregation 交换机互联
    for p in range(pods):
        for e in range(num_edge_per_pod):
            edge_id = edge_map[(p, e)]
            for a in range(num_agg_per_pod):
                agg_id = agg_map[(p, a)]
                links.append((edge_id, agg_id, bw, delay, loss))

    # (c) 每个 pod 内的 aggregation 交换机与 core 交换机按照 fat-tree 规则连接
    for p in range(pods):
        for a in range(num_agg_per_pod):
            agg_id = agg_map[(p, a)]
            for j in range(k // 2):
                core_index = a * (k // 2) + j
                core_id = core_switches[core_index]
                links.append((agg_id, core_id, bw, delay, loss))

    # (d) DCI 交换机与每个 core 交换机相连
    for core_id in core_switches:
        links.append((dci_switch, core_id, '100Gbps', delay, loss))

    # 汇总所有交换机（顺序为：edge, agg, core, dci）
    switches = edge_switches + agg_switches + core_switches

    return hosts, switches, links, dci_switch

def generate_as_topology(as_id, k):
    """
    为一个 AS（DC）生成 fat-tree 拓扑，并以字典形式返回
    """
    hosts, switches, links, dci_switch = generate_fattree_topology(k)
    num_switches = len(switches)
    num_hosts = len(hosts)
    
    as_topology = {
        "dci_switch": dci_switch,
        "as_id": as_id,
        "num_switches": num_switches,
        "num_hosts": num_hosts,
        "switches": switches,
        "hosts": hosts,
        "links": [
            {"src": link[0], "dst": link[1], "bw": link[2], "delay": link[3], "loss": link[4]}
            for link in links
        ]
    }
    return as_topology

def generate_topology_file(num_as, k_values):
    """
    生成整个网络拓扑描述文件（返回字典）：
      - 包含 AS 数量和每个 AS 的内部 fat-tree 拓扑信息
      - 广域网部分由用户后续手动配置（此处不生成）
    """
    topology = {"num_as": num_as, "as_topologies": []}
    for as_id, k in enumerate(k_values):
        as_topology = generate_as_topology(as_id, k)
        topology["as_topologies"].append(as_topology)
    return topology

# 判断是否为简单值（int, float, str, bool, None）
def is_simple_value(x):
    return isinstance(x, (int, float, str, bool)) or x is None

def custom_json_dumps(obj, indent=4, level=0):
    """
    自定义 JSON 序列化函数：
      - 对于列表：如果所有元素都是简单值，则输出在一行；否则采用多行格式化
      - 对于字典：如果所有值都是简单类型，则输出在一行；否则采用多行格式化
    """
    spacing = " " * (indent * level)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        # 判断字典中所有值是否都是简单类型
        if all(is_simple_value(v) for v in obj.values()):
            items = [f'"{k}": {custom_json_dumps(v, indent, 0)}' for k, v in obj.items()]
            return "{" + ", ".join(items) + "}"
        else:
            items = []
            for k, v in obj.items():
                formatted_value = custom_json_dumps(v, indent, level+1)
                items.append(f'{spacing}{" " * indent}"{k}": {formatted_value}')
            return "{\n" + ",\n".join(items) + "\n" + spacing + "}"
    elif isinstance(obj, list):
        if not obj:
            return "[]"
        # 判断列表中是否全为简单值
        if all(is_simple_value(item) for item in obj):
            inline = ", ".join(custom_json_dumps(item, indent, 0) for item in obj)
            return f"[{inline}]"
        else:
            items = []
            for item in obj:
                items.append(" " * (indent * (level+1)) + custom_json_dumps(item, indent, level+1))
            return "[\n" + ",\n".join(items) + "\n" + spacing + "]"
    else:
        return json.dumps(obj)

if __name__ == "__main__":
    # 重置全局节点计数器
    next_node_id = 0

    # 示例参数：3个 AS，每个 AS 的 fat-tree 参数 k=4（注意 k 必须为偶数）
    num_as = 3
    k_values = [4, 4, 4]
    topology = generate_topology_file(num_as, k_values)
    topology['wan_switch_num'] = 2
    topology['wan_link_num'] = 6
    topology['wan_switches'] = [111]
    topology['wan_links'] = [
        {"src": 36, "dst": 111, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        #{"src": 36, "dst": 112, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": 73, "dst": 111, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        #{"src": 73, "dst": 112, "bw": '400Gbps', "delay": '400us', "loss": 0.0},
        {"src": 110, "dst": 111, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        #{"src": 110, "dst": 112, "bw": '400Gbps', "delay": '500us', "loss": 0.0}
    ]
    topology['as_delay'] = [
        {"src":0, "dst":1, "delay":1000000},
        {"src":0, "dst":2, "delay":1000000},
        {"src":1, "dst":2, "delay":1000000},
    ]
    topology['wan_routing'] = [
        {"srcSw":36, "dstAs":1, "next_nodes":[111]},
        {"srcSw":36, "dstAs":2, "next_nodes":[111]},
        {"srcSw":73, "dstAs":0, "next_nodes":[111]},
        {"srcSw":73, "dstAs":2, "next_nodes":[111]},
        {"srcSw":110, "dstAs":0, "next_nodes":[111]},
        {"srcSw":110, "dstAs":1, "next_nodes":[111]},
        {"srcSw":111, "dstAs":0, "next_nodes":[36]},
        {"srcSw":111, "dstAs":1, "next_nodes":[73]},
        {"srcSw":111, "dstAs":2, "next_nodes":[110]},
    ]
    topology_json = custom_json_dumps(topology, indent=4)
    with open(op.join(op.dirname(__file__), 'wan_topo_json.txt'), 'w') as f:
        f.write(topology_json)
