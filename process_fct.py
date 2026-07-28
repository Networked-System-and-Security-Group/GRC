import sys
import os
import pandas as pd
import re

# Add the project root to sys.path to import from analysis
sys.path.append('/home/zhangj25/RDMA-WAN-Optimization')
from analysis.deep_analyse import get_basic_result

def get_family(dir_name):
    if '0.25-' in dir_name:
        if 'w_6m' in dir_name: return '200ms run 6MB 0.25guarantee'
        if 'w_7m' in dir_name: return '200ms run 7MB 0.25guarantee'
    else:
        if 'w_8m' in dir_name: return '200ms run'
        if 'w_6m' in dir_name: return '200ms run 6MB'
        if 'w_7m' in dir_name: return '200ms run 7MB'
    return 'Unknown'

def get_load(dir_name):
    match = re.search(r'150-(\d+)', dir_name)
    return match.group(1) if match else 'Unknown'

def get_scheme(dir_name):
    if 'gscc_w_' in dir_name:
        if '_fair-flow' in dir_name: return 'K_fair'
        return 'K_noFair'
    else:
        if 'gscc_20m_fair-flow' in dir_name: return 'noK_fair'
        if 'gscc_20m-flow' in dir_name: return 'noK_noFair'
    return 'Unknown'

results = get_basic_result('112-191')
data = []
for dir_name, metrics in results.items():
    family = get_family(dir_name)
    load = get_load(dir_name)
    scheme = get_scheme(dir_name)
    
    row = {
        'ID': dir_name,
        'family': family,
        'load': load,
        'scheme': scheme,
        'Avg_FCT': metrics.get('Avg_FCT'),
        'Avg_Intra_FCT': metrics.get('Avg_Intra_FCT'),
        'Avg_Inter_FCT': metrics.get('Avg_Inter_FCT'),
        'P99_FCT': metrics.get('P99_FCT'),
        'P99_Intra_FCT': metrics.get('P99_Intra_FCT'),
        'P99_Inter_FCT': metrics.get('P99_Inter_FCT')
    }
    data.append(row)

df = pd.DataFrame(data)

# Save Detail
df.to_csv('/home/zhangj25/RDMA-WAN-Optimization/mix/output/fct_112_191_detail.csv', index=False)

# Summary by family+load+scheme
summary = df.groupby(['family', 'load', 'scheme']).mean().reset_index()
summary.to_csv('/home/zhangj25/RDMA-WAN-Optimization/mix/output/fct_112_191_summary.csv', index=False)

# Aggregation by family+scheme (mean across loads)
agg_cols = ['P99_FCT', 'P99_Intra_FCT', 'P99_Inter_FCT', 'Avg_FCT']
family_scheme_mean = summary.groupby(['family', 'scheme'])[agg_cols].mean().reset_index()
family_scheme_mean.to_csv('/home/zhangj25/RDMA-WAN-Optimization/mix/output/fct_112_191_family_scheme_mean.csv', index=False)

# Prints
print("\n--- Family Experiment Counts ---")
print(df['family'].value_counts())

print("\n--- Completeness Check (Expecting 16 per family) ---")
for family in df['family'].unique():
    subset = df[df['family'] == family]
    count = len(subset)
    if count != 16:
        print(f"Family '{family}' has {count} experiments (expected 16).")
        # Find missing load/scheme combinations
        all_loads = ['0', '60', '120', '180']
        all_schemes = ['noK_noFair', 'noK_fair', 'K_noFair', 'K_fair']
        existing = set(zip(subset['load'], subset['scheme']))
        for l in all_loads:
            for s in all_schemes:
                if (l, s) not in existing:
                    print(f"  Missing: Load={l}, Scheme={s}")

print("\n--- P99_Inter_FCT Ranking (by family+scheme, lower is better) ---")
ranked = family_scheme_mean.sort_values('P99_Inter_FCT')
print(ranked[['family', 'scheme', 'P99_Inter_FCT']].to_string(index=False))

