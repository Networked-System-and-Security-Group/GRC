import json
import os.path as op

next_node_id = 0
dci_switches = []

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
    dci_switches.append(dci_switch)

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
        links.append((dci_switch, core_id, '200Gbps', delay, loss))

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

def generate_cernet_topo():
    """
    生成一个基于CERNET骨干网的特定拓扑。
    - WAN: 包含北京、天津、石家庄、太原、呼和浩特5个核心节点。
    - LAN: 6个AS(Fat-Tree, k=4)分别连接到指定的WAN节点。
    """
    global next_node_id, dci_switches
    # 重置全局计数器和列表，确保每次调用都从头开始生成
    next_node_id = 0
    dci_switches = []

    # 1. 生成所有自治域 (AS) 的拓扑
    # 总共需要 1(北京) + 1(天津) + 1(石家庄) + 2(呼和浩特) + 1(太原) = 6个AS
    num_as = 6
    k_values = [4] * num_as  # 所有AS都使用k=4的Fat-Tree
    # 调用现有函数生成AS拓扑，这将填充全局的 dci_switches 列表
    topology = generate_topology_file(num_as, k_values)

    # 2. 定义广域网 (WAN) 拓扑
    wan_cities = ['北京', '天津', '石家庄', '太原', '呼和浩特']
    wan_switch_map = {city: get_next_id() for city in wan_cities}
    wan_switches_list = list(wan_switch_map.values())
    
    # 3. 定义并创建WAN链路
    wan_links_info = [
        ('北京', '天津', 108), ('北京', '石家庄', 265.62), ('北京', '呼和浩特', 415.29),
        ('北京', '太原', 402), ('石家庄', '天津', 265), ('呼和浩特', '太原', 336)
    ]
    
    wan_links = []
    wan_bw = '400Gbps'
    
    for src_city, dst_city, distance in wan_links_info:
        # 延迟计算：200km = 1ms = 1000us
        delay_us = (distance / 200.0) * 1000
        delay_str = f"{int(delay_us)}us"
        wan_links.append({
            "src": wan_switch_map[src_city],
            "dst": wan_switch_map[dst_city],
            "bw": wan_bw,
            "delay": delay_str,
            "loss": 0.0
        })

    # 4. 创建AS (DCI交换机) 与 WAN交换机的连接链路
    # dci_switches 列表中的DCI交换机是按AS ID顺序生成的 (AS0, AS1, ...)
    dci_to_wan_connections = [
        (dci_switches[0], '北京'),
        (dci_switches[1], '天津'),
        (dci_switches[2], '石家庄'),
        (dci_switches[3], '呼和浩特'), # 第一个连接到呼和浩特的AS
        (dci_switches[4], '呼和浩特'), # 第二个连接到呼和浩特的AS
        (dci_switches[5], '太原')
    ]

    dci_wan_delay = '300us'
    for dci_id, city in dci_to_wan_connections:
        wan_links.append({
            "src": dci_id,
            "dst": wan_switch_map[city],
            "bw": wan_bw, 
            "delay": dci_wan_delay,
            "loss": 0.0
        })

    # 5. 在每个WAN交换机上绑定5个host
    wan_hosts = []
    wan_host_links = []
    wan_host_bw = '60Gbps'
    wan_host_delay = '1000ns'
    wan_host_loss = 0.0

    for wan_switch in wan_switches_list:
        for _ in range(20):  # 每个WAN交换机绑定20个host
            host_id = get_next_id()
            wan_hosts.append(host_id)
            wan_host_links.append({
                "src": wan_switch,
                "dst": host_id,
                "bw": wan_host_bw,
                "delay": wan_host_delay,
                "loss": wan_host_loss
            })

    # 将WAN链路和WAN主机链路合并
    wan_links.extend(wan_host_links)

    # 6. 将WAN信息整合到最终的拓扑字典中
    topology['wan_switch_num'] = len(wan_switches_list)
    topology['wan_switches'] = wan_switches_list
    topology['wan_links'] = wan_links
    topology['wan_link_num'] = len(wan_links)
    topology['wan_hosts'] = wan_hosts
    topology['wan_host_num'] = len(wan_hosts)

    with open(op.join(op.dirname(__file__), 'cernet_topo.txt'), 'w') as f:
        topology_json = custom_json_dumps(topology, indent=4)
        f.write(topology_json)

if __name__ == "__main__":
    # 重置全局节点计数器
    generate_cernet_topo()
    quit(0)
    next_node_id = 0

    # 示例参数：3个 AS，每个 AS 的 fat-tree 参数 k=4（注意 k 必须为偶数）
    num_as = 6
    k_values = [4, 4, 4, 4, 4, 4]
    topology = generate_topology_file(num_as, k_values)
    topology['wan_switch_num'] = 3
    topology['wan_link_num'] = 9
    wan0 = get_next_id()
    wan1 = get_next_id()
    wan2 = get_next_id()
    topology['wan_switches'] = [wan0, wan1, wan2]
    dci0, dci1, dci2, dci3, dci4, dci5 = dci_switches[0], dci_switches[1], dci_switches[2], dci_switches[3], dci_switches[4], dci_switches[5]
    topology['wan_links'] = [
        {"src": wan0, "dst": dci0, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan0, "dst": dci1, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan1, "dst": dci2, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan1, "dst": dci3, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan2, "dst": dci4, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan2, "dst": dci5, "bw": '400Gbps', "delay": '500us', "loss": 0.0},
        {"src": wan0, "dst": wan1, "bw": '400Gbps', "delay": '1500us', "loss": 0.0},
        {"src": wan0, "dst": wan2, "bw": '400Gbps', "delay": '2000us', "loss": 0.0},
        {"src": wan1, "dst": wan2, "bw": '400Gbps', "delay": '2400us', "loss": 0.0},
    ]
    topology_json = custom_json_dumps(topology, indent=4)
    with open(op.join(op.dirname(__file__), 'wan_topo_large.txt'), 'w') as f:
        f.write(topology_json)
