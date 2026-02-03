import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
import sys
from deep_analyse import get_analyser

# Experiment Parameters
DYNAMICS = [0, 50, 100, 150, 200]
BETAS = [0.5, 0.4, 0.3, 0.2, 0.1, 0]

# Experiment ID ranges
# Set 1: Disable V (105-134)
START_ID_NO_V = 105
# Set 2: Enable V (135-164)
START_ID_WITH_V = 135

# Metric Selection
# Options: 'inter_avg_fct', 'wan_buffer_avg', 'wan_buffer_p99'
METRIC = 'inter_avg_fct' 

def get_metric_label(metric_key):
    if metric_key == 'inter_avg_fct':
        return 'Avg Inter FCT Slowdown'
    elif metric_key == 'wan_buffer_avg':
        return 'Avg WAN Buffer (Bytes)'
    elif metric_key == 'wan_buffer_p99':
        return 'P99 WAN Buffer (Bytes)'
    return metric_key

def collect_data(start_id, label, metric_key):
    data = []
    current_id = start_id
    
    print(f"Collecting data for {label} (Starting ID: {start_id}, Metric: {metric_key})...")
    
    for dyn in DYNAMICS:
        for beta in BETAS:
            print(f"Processing ID: {current_id} (Dyn={dyn}, Beta={beta})")
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
                    'Dynamic': dyn,
                    'Beta': beta,
                    'Value': value,
                    'Experiment': label
                })
            except Exception as e:
                print(f"Error processing ID {current_id}: {e}")
                data.append({
                    'Dynamic': dyn,
                    'Beta': beta,
                    'Value': np.nan,
                    'Experiment': label
                })
            current_id += 1
            
    return pd.DataFrame(data)

def plot_heatmap(df, title, filename, z_label):
    pivot_table = df.pivot(index='Beta', columns='Dynamic', values='Value')
    pivot_table = pivot_table.sort_index(ascending=True) 
    
    plt.figure(figsize=(8, 6))
    sns.heatmap(pivot_table, annot=True, fmt=".2f", cmap="viridis_r", cbar_kws={'label': z_label})
    plt.title(title)
    plt.xlabel("Dynamic Load")
    plt.ylabel("Beta")
    plt.tight_layout()
    plt.savefig(filename)
    print(f"Saved heatmap to {filename}")
    plt.close()

def plot_single_3d(df, title, filename, z_label):
    """
    Plots a single surface on a 3D plot.
    Axes: X=Beta, Y=Dynamic Load.
    """
    pivot = df.pivot(index='Dynamic', columns='Beta', values='Value')
    pivot = pivot.sort_index(ascending=True)      # Sort Dynamic
    pivot = pivot.sort_index(axis=1, ascending=True) # Sort Beta
    
    X_vals = pivot.columns.values # Beta
    Y_vals = pivot.index.values   # Dynamic
    X, Y = np.meshgrid(X_vals, Y_vals)
    Z = pivot.values

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection='3d')
    
    surf = ax.plot_surface(X, Y, Z, cmap='viridis', edgecolor='k', linewidth=0.5, alpha=0.9)
    
    ax.set_title(title)
    ax.set_xlabel('Beta')         
    ax.set_ylabel('Dynamic Load') 
    ax.set_zlabel(z_label)
    
    fig.colorbar(surf, ax=ax, shrink=0.5, aspect=5, label=z_label)
    
    plt.tight_layout()
    plt.savefig(filename)
    print(f"Saved 3D plot to {filename}")
    plt.close()

def plot_combined_3d(df1, label1, df2, label2, title, filename, z_label):
    """
    Plots two surfaces on the same 3D plot.
    Axes: X=Beta, Y=Dynamic Load.
    """
    def get_xyz(df):
        pivot = df.pivot(index='Dynamic', columns='Beta', values='Value')
        pivot = pivot.sort_index(ascending=True)      
        pivot = pivot.sort_index(axis=1, ascending=True) 
        
        X_vals = pivot.columns.values 
        Y_vals = pivot.index.values   
        X, Y = np.meshgrid(X_vals, Y_vals)
        Z = pivot.values
        return X, Y, Z

    X1, Y1, Z1 = get_xyz(df1)
    X2, Y2, Z2 = get_xyz(df2)
    
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # Plot Surface 1 (df1) - Blues
    surf1 = ax.plot_surface(X1, Y1, Z1, cmap='Blues', alpha=0.8, edgecolor='k', linewidth=0.2)
    
    # Plot Surface 2 (df2) - Oranges
    surf2 = ax.plot_surface(X2, Y2, Z2, cmap='Oranges', alpha=0.8, edgecolor='k', linewidth=0.2)
    
    ax.set_title(title)
    ax.set_xlabel('Beta')         
    ax.set_ylabel('Dynamic Load') 
    ax.set_zlabel(z_label)
    
    # Custom Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='blue', edgecolor='k', label=label1, alpha=0.5),
        Patch(facecolor='orange', edgecolor='k', label=label2, alpha=0.5)
    ]
    ax.legend(handles=legend_elements)
    
    plt.tight_layout()
    plt.savefig(filename)
    print(f"Saved combined 3D plot to {filename}")
    plt.close()

def main():
    # Allow overriding metric via arg (simple hack)
    global METRIC
    if len(sys.argv) > 1:
        METRIC = sys.argv[1]

    z_label = get_metric_label(METRIC)
    
    # 1. Collect Data
    df_no_v = collect_data(START_ID_NO_V, "Disable V", METRIC)
    df_with_v = collect_data(START_ID_WITH_V, "Enable V", METRIC)
    
    # 2. Plot Separate 3D Surfaces
    plot_single_3d(df_no_v, f"{z_label} (Disable V)", f"sens_{METRIC}_no_v_3d.pdf", z_label)
    plot_single_3d(df_with_v, f"{z_label} (Enable V)", f"sens_{METRIC}_with_v_3d.pdf", z_label)

    # 3. Plot Combined 3D Surface
    plot_combined_3d(df_no_v, "Disable V", df_with_v, "Enable V", 
                     f"{z_label} (Comparison)", 
                     f"sens_{METRIC}_combined_3d.pdf", z_label)

    # 4. Save CSV
    combined_df = pd.concat([df_no_v, df_with_v])
    combined_df.to_csv(f"sens_{METRIC}_results.csv", index=False)
    print(f"Saved results to sens_{METRIC}_results.csv")

if __name__ == "__main__":
    main()
