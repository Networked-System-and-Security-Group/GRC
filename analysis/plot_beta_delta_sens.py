import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import sys
from deep_analyse import get_analyser

# Experiment Parameters (Deduced from history [210]-[233])
# Note: History shows BETAS=[0, 0.1, 0.2, 0.3, 0.4, 0.5]
# INV_DELTAS=[2621440, 5242880, 10485760, 20971520]
# Order in history: Outer loop INV_DELTA, Inner loop BETA.

BETAS = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
INV_DELTAS = [2621440, 5242880, 10485760, 20971520]
START_ID = 210

# Metric Selection
METRIC = 'inter_avg_fct' 

def get_metric_label(metric_key):
    if metric_key == 'inter_avg_fct':
        return 'Avg Inter FCT Slowdown'
    elif metric_key == 'wan_buffer_avg':
        return 'Avg WAN Buffer (Bytes)'
    elif metric_key == 'wan_buffer_p99':
        return 'P99 WAN Buffer (Bytes)'
    return metric_key

def collect_data(start_id, metric_key):
    data = []
    current_id = start_id
    
    print(f"Collecting data (Starting ID: {start_id}, Metric: {metric_key})...")
    
    for inv_delta in INV_DELTAS:
        for beta in BETAS:
            print(f"Processing ID: {current_id} (InvDelta={inv_delta}, Beta={beta})")
            try:
                ana = get_analyser(current_id)
                value = np.nan
                
                if metric_key == 'inter_avg_fct':
                    # get_avg_fct returns (avg, intra, inter)
                    _, _, value = ana.get_avg_fct()
                elif metric_key == 'wan_buffer_avg':
                    mean, _ = ana.get_wan_buffer_stats()
                    value = mean
                elif metric_key == 'wan_buffer_p99':
                    _, p99 = ana.get_wan_buffer_stats()
                    value = p99
                
                data.append({
                    'InvDelta': inv_delta,
                    'Beta': beta,
                    'Value': value
                })
            except Exception as e:
                print(f"Error processing ID {current_id}: {e}")
                data.append({
                    'InvDelta': inv_delta,
                    'Beta': beta,
                    'Value': np.nan
                })
            current_id += 1
            
    return pd.DataFrame(data)

def plot_heatmap(df, title, filename, z_label):
    # Pivot: Index=Beta, Columns=InvDelta
    pivot_table = df.pivot(index='Beta', columns='InvDelta', values='Value')
    pivot_table = pivot_table.sort_index(ascending=True) 
    
    plt.figure(figsize=(10, 8))
    sns.heatmap(pivot_table, annot=True, fmt=".2f", cmap="viridis_r", cbar_kws={'label': z_label})
    plt.title(title)
    plt.xlabel("Inv Delta")
    plt.ylabel("Beta")
    plt.tight_layout()
    plt.savefig(filename)
    print(f"Saved heatmap to {filename}")
    plt.close()

def plot_3d(df, title, filename, z_label):
    """
    Plots a single surface on a 3D plot.
    Axes: X=InvDelta, Y=Beta
    """
    pivot = df.pivot(index='Beta', columns='InvDelta', values='Value')
    pivot = pivot.sort_index(ascending=True)      
    pivot = pivot.sort_index(axis=1, ascending=True) 
    
    X_vals = pivot.columns.values # InvDelta
    Y_vals = pivot.index.values   # Beta
    X, Y = np.meshgrid(X_vals, Y_vals)
    Z = pivot.values

    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    surf = ax.plot_surface(X, Y, Z, cmap='viridis', edgecolor='k', linewidth=0.5, alpha=0.9)
    
    ax.set_title(title)
    ax.set_xlabel('Inv Delta')         
    ax.set_ylabel('Beta') 
    ax.set_zlabel(z_label)
    
    fig.colorbar(surf, ax=ax, shrink=0.5, aspect=5, label=z_label)
    
    plt.tight_layout()
    plt.savefig(filename)
    print(f"Saved 3D plot to {filename}")
    plt.close()

def main():
    global METRIC
    if len(sys.argv) > 1:
        METRIC = sys.argv[1]

    z_label = get_metric_label(METRIC)
    
    # 1. Collect Data
    df = collect_data(START_ID, METRIC)
    
    # 2. Plot
    plot_heatmap(df, f"{z_label} (Beta vs InvDelta)", f"beta_delta_{METRIC}_heatmap.pdf", z_label)
    plot_3d(df, f"{z_label} (Beta vs InvDelta)", f"beta_delta_{METRIC}_3d.pdf", z_label)

    # 3. Save CSV
    df.to_csv(f"beta_delta_{METRIC}_results.csv", index=False)
    print(f"Saved results to beta_delta_{METRIC}_results.csv")

if __name__ == "__main__":
    main()
