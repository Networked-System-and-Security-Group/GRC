import sys

def generate_topology_stdout(as_k_list):
    as_list = []
    all_dci_switches = []
    global_switch_counter = 0
    global_host_counter = 0

    for as_index, k in enumerate(as_k_list):
        dci_id = global_switch_counter
        global_switch_counter += 1
        all_dci_switches.append(dci_id)

        num_core = (k // 2) ** 2
        num_aggregation = k * (k // 2)
        num_edge = k * (k // 2)

        core_switches = list(range(global_switch_counter, global_switch_counter + num_core))
        global_switch_counter += num_core
        agg_switches = list(range(global_switch_counter, global_switch_counter + num_aggregation))
        global_switch_counter += num_aggregation
        edge_switches = list(range(global_switch_counter, global_switch_counter + num_edge))
        global_switch_counter += num_edge

        num_hosts = (k // 2) * num_edge
        host_list = list(range(global_host_counter, global_host_counter + num_hosts))
        global_host_counter += num_hosts

        links = []
        
        # Core to Aggregation
        for c in core_switches:
            c_idx = c - core_switches[0]
            i = c_idx // (k//2)
            j = c_idx % (k//2)
            for p in range(k):
                agg_idx = p * (k//2) + j
                links.append((c, agg_switches[agg_idx], '100Gbps', '1000ns', 0))
        
        # Aggregation to Edge
        for p in range(k):
            for a in range(k//2):
                agg_sw = agg_switches[p * (k//2) + a]
                for e in range(k//2):
                    edge_sw = edge_switches[p * (k//2) + e]
                    links.append((agg_sw, edge_sw, '100Gbps', '1000ns', 0))
        
        # Edge to Hosts
        host_idx = 0
        for e_sw in edge_switches:
            for _ in range(k//2):
                links.append((e_sw, host_list[host_idx], '100Gbps', '1000ns', 0))
                host_idx += 1
        
        # Core to DCI
        for c in core_switches:
            links.append((c, dci_id, '100Gbps', '1000ns', 0))

        switches = [dci_id] + core_switches + agg_switches + edge_switches
        
        as_list.append({
            'dci_id': dci_id,
            'as_number': as_index,
            'subnet': f'10.{as_index}.0.0',
            'switches': switches,
            'hosts': host_list,
            'links': links
        })

    # 输出到标准输出
    print(len(as_list))
    for asys in as_list:
        print(asys['dci_id'])
        print(asys['as_number'])
        print(asys['subnet'])
        print(len(asys['switches']), len(asys['hosts']))
        print(' '.join(map(str, asys['switches'])))
        print(' '.join(map(str, asys['hosts'])))
        print(len(asys['links']))
        for link in asys['links']:
            print(f"{link[0]} {link[1]} {link[2]} {link[3]} {link[4]}")
    
    # 广域网部分
    print(len(all_dci_switches), 0)
    print(' '.join(map(str, all_dci_switches)))

# 示例调用
generate_topology_stdout([4, 4])
