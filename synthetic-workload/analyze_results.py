#!/usr/bin/env python3
"""
analyze_results.py — Parse perf stat output and program RESULT lines,
aggregate across repetitions, generate comparison charts and CSV.
"""

import os
import re
import csv
import sys
from collections import defaultdict

# Use the venv's matplotlib backend
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

RAW_DIR = os.path.join(os.path.dirname(__file__), 'raw_results')
PLOTS_DIR = os.path.join(os.path.dirname(__file__), 'plots')
CSV_PATH = os.path.join(os.path.dirname(__file__), 'results.csv')

os.makedirs(PLOTS_DIR, exist_ok=True)


def parse_perf_file(filepath):
    """Parse a perf stat output file into a dict of metric -> value."""
    metrics = {}
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            # Match lines like: "262,278      page-faults"
            m = re.match(r'^([\d,]+)\s+(\S+)', line)
            if m:
                val_str = m.group(1).replace(',', '')
                name = m.group(2)
                metrics[name] = int(val_str)
            # Match "seconds time elapsed"
            m2 = re.match(r'^([\d.]+)\s+seconds time elapsed', line)
            if m2:
                metrics['wall_time_sec'] = float(m2.group(1))
            # Match IPC: "# X.XX insn per cycle"
            m3 = re.search(r'#\s+([\d.]+)\s+insn per cycle', line)
            if m3:
                metrics['IPC'] = float(m3.group(1))
    return metrics


def parse_output_file(filepath):
    """Parse the RESULT line from program output."""
    result = {}
    with open(filepath) as f:
        for line in f:
            if line.startswith('RESULT:'):
                for part in line.strip().split()[1:]:
                    key, val = part.split('=')
                    try:
                        result[key] = float(val)
                    except ValueError:
                        result[key] = val
    return result


def discover_experiments():
    """Discover all experiment result files and group them."""
    experiments = defaultdict(list)

    for fname in os.listdir(RAW_DIR):
        if not fname.endswith('_perf.txt'):
            continue
        label = fname.replace('_perf.txt', '')
        # Parse label: pattern_strideN_PageConfig_repN
        # e.g., seq_stride1_4KB_rep1, stride_stride4096_2MB_rep2
        parts = label.rsplit('_rep', 1)
        if len(parts) != 2:
            continue
        config_key = parts[0]  # e.g., seq_stride1_4KB
        rep = int(parts[1])

        perf_file = os.path.join(RAW_DIR, fname)
        output_file = os.path.join(RAW_DIR, label + '_output.txt')

        perf_data = parse_perf_file(perf_file)
        output_data = parse_output_file(output_file) if os.path.exists(output_file) else {}

        # Merge
        data = {**perf_data, **output_data}
        data['rep'] = rep
        data['config_key'] = config_key
        experiments[config_key].append(data)

    return experiments


def aggregate(experiments):
    """Compute mean and std for each config across repetitions."""
    results = []
    numeric_keys = [
        'page-faults', 'minor-faults', 'major-faults',
        'dTLB-load-misses', 'dTLB-store-misses', 'iTLB-load-misses',
        'cycles', 'instructions', 'wall_time_sec', 'IPC', 'time_sec'
    ]

    for config_key, reps in sorted(experiments.items()):
        row = {'config': config_key}

        # Parse config key
        # Examples: seq_stride1_4KB, rand_stride1_2MB, stride_stride4096_4KB
        parts = config_key.split('_')
        row['pattern'] = parts[0]
        row['stride'] = parts[1].replace('stride', '')
        row['page_config'] = parts[2]

        for key in numeric_keys:
            vals = [r.get(key) for r in reps if r.get(key) is not None]
            if vals:
                row[f'{key}_mean'] = np.mean(vals)
                row[f'{key}_std'] = np.std(vals)
            else:
                row[f'{key}_mean'] = 0
                row[f'{key}_std'] = 0

        results.append(row)

    return results


def save_csv(results, path):
    """Save aggregated results to CSV."""
    if not results:
        return
    keys = results[0].keys()
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved CSV: {path}")


def get_display_label(row):
    """Create a readable label for a config."""
    pattern = row['pattern']
    stride = row['stride']
    if pattern == 'stride':
        return f"stride-{stride}"
    return pattern


def create_comparison_charts(results):
    """Generate bar charts comparing 4KB vs 2MB for key metrics."""
    # Group by pattern (with stride) for x-axis
    patterns_order = []
    seen = set()
    for r in results:
        label = get_display_label(r)
        if label not in seen:
            patterns_order.append(label)
            seen.add(label)

    # Build data lookup: metric -> pattern -> page_config -> value
    data_lookup = {}
    for r in results:
        label = get_display_label(r)
        pc = r['page_config']
        data_lookup.setdefault(label, {})[pc] = r

    # Color scheme
    colors_4kb = '#4A90D9'
    colors_2mb = '#E74C3C'

    # ===== Chart 1: Page Faults =====
    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.arange(len(patterns_order))
    width = 0.35

    vals_4kb = [data_lookup[p].get('4KB', {}).get('page-faults_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('page-faults_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('page-faults_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('page-faults_std', 0) for p in patterns_order]

    bars1 = ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    bars2 = ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('Page Faults (count)', fontsize=12)
    ax.set_title('Page Faults: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'page_faults.png'), dpi=150)
    plt.close()
    print("Generated: page_faults.png")

    # ===== Chart 2: dTLB Load Misses =====
    fig, ax = plt.subplots(figsize=(10, 6))
    vals_4kb = [data_lookup[p].get('4KB', {}).get('dTLB-load-misses_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('dTLB-load-misses_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('dTLB-load-misses_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('dTLB-load-misses_std', 0) for p in patterns_order]

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('dTLB Load Misses (count)', fontsize=12)
    ax.set_title('dTLB Load Misses: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'dtlb_load_misses.png'), dpi=150)
    plt.close()
    print("Generated: dtlb_load_misses.png")

    # ===== Chart 3: Execution Time =====
    fig, ax = plt.subplots(figsize=(10, 6))
    vals_4kb = [data_lookup[p].get('4KB', {}).get('time_sec_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('time_sec_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('time_sec_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('time_sec_std', 0) for p in patterns_order]

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('Execution Time (seconds)', fontsize=12)
    ax.set_title('Execution Time: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'execution_time.png'), dpi=150)
    plt.close()
    print("Generated: execution_time.png")

    # ===== Chart 4: IPC =====
    fig, ax = plt.subplots(figsize=(10, 6))
    vals_4kb = [data_lookup[p].get('4KB', {}).get('IPC_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('IPC_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('IPC_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('IPC_std', 0) for p in patterns_order]

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('Instructions Per Cycle (IPC)', fontsize=12)
    ax.set_title('IPC: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'ipc.png'), dpi=150)
    plt.close()
    print("Generated: ipc.png")

    # ===== Chart 5: CPU Cycles =====
    fig, ax = plt.subplots(figsize=(10, 6))
    vals_4kb = [data_lookup[p].get('4KB', {}).get('cycles_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('cycles_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('cycles_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('cycles_std', 0) for p in patterns_order]

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('CPU Cycles', fontsize=12)
    ax.set_title('CPU Cycles: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'cpu_cycles.png'), dpi=150)
    plt.close()
    print("Generated: cpu_cycles.png")

    # ===== Chart 6: dTLB Store Misses =====
    fig, ax = plt.subplots(figsize=(10, 6))
    vals_4kb = [data_lookup[p].get('4KB', {}).get('dTLB-store-misses_mean', 0) for p in patterns_order]
    vals_2mb = [data_lookup[p].get('2MB', {}).get('dTLB-store-misses_mean', 0) for p in patterns_order]
    errs_4kb = [data_lookup[p].get('4KB', {}).get('dTLB-store-misses_std', 0) for p in patterns_order]
    errs_2mb = [data_lookup[p].get('2MB', {}).get('dTLB-store-misses_std', 0) for p in patterns_order]

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=colors_4kb, yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=colors_2mb, yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Access Pattern', fontsize=12)
    ax.set_ylabel('dTLB Store Misses (count)', fontsize=12)
    ax.set_title('dTLB Store Misses: 4 KB vs 2 MB Pages', fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(patterns_order, fontsize=11)
    ax.legend(fontsize=11)
    ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'dtlb_store_misses.png'), dpi=150)
    plt.close()
    print("Generated: dtlb_store_misses.png")

    # ===== Chart 7: Percentage improvement summary =====
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Page fault reduction
    ax = axes[0]
    reductions = []
    labels = []
    for p in patterns_order:
        v4 = data_lookup[p].get('4KB', {}).get('page-faults_mean', 1)
        v2 = data_lookup[p].get('2MB', {}).get('page-faults_mean', 1)
        pct = (v4 - v2) / v4 * 100 if v4 > 0 else 0
        reductions.append(pct)
        labels.append(p)

    bars = ax.bar(labels, reductions, color='#2ECC71', edgecolor='#27AE60', linewidth=1.5)
    ax.set_ylabel('Reduction (%)', fontsize=12)
    ax.set_title('Page Fault Reduction\n(4KB → 2MB)', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 105)
    for bar, val in zip(bars, reductions):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # dTLB load miss reduction
    ax = axes[1]
    reductions = []
    for p in patterns_order:
        v4 = data_lookup[p].get('4KB', {}).get('dTLB-load-misses_mean', 1)
        v2 = data_lookup[p].get('2MB', {}).get('dTLB-load-misses_mean', 1)
        pct = (v4 - v2) / v4 * 100 if v4 > 0 else 0
        reductions.append(pct)

    bars = ax.bar(labels, reductions, color='#3498DB', edgecolor='#2980B9', linewidth=1.5)
    ax.set_ylabel('Reduction (%)', fontsize=12)
    ax.set_title('dTLB Load Miss Reduction\n(4KB → 2MB)', fontsize=13, fontweight='bold')
    ax.set_ylim(0, 105)
    for bar, val in zip(bars, reductions):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'improvement_summary.png'), dpi=150)
    plt.close()
    print("Generated: improvement_summary.png")


def print_summary(results):
    """Print a summary table to stdout."""
    print("\n" + "="*100)
    print("SYNTHETIC WORKLOAD RESULTS SUMMARY")
    print("="*100)
    fmt = "{:<20} {:>15} {:>15} {:>18} {:>12} {:>10}"
    print(fmt.format("Config", "Page Faults", "dTLB-Load-Miss", "dTLB-Store-Miss", "IPC", "Time(s)"))
    print("-"*100)
    for r in results:
        label = f"{get_display_label(r)} ({r['page_config']})"
        print(fmt.format(
            label,
            f"{r['page-faults_mean']:,.0f} ±{r['page-faults_std']:,.0f}",
            f"{r['dTLB-load-misses_mean']:,.0f}",
            f"{r['dTLB-store-misses_mean']:,.0f}",
            f"{r['IPC_mean']:.2f}",
            f"{r['time_sec_mean']:.4f}"
        ))
    print("="*100)


def main():
    print("Discovering experiments...")
    experiments = discover_experiments()
    print(f"Found {len(experiments)} configurations, {sum(len(v) for v in experiments.values())} total runs")

    print("\nAggregating results...")
    results = aggregate(experiments)

    print("\nSaving CSV...")
    save_csv(results, CSV_PATH)

    print("\nGenerating charts...")
    create_comparison_charts(results)

    print_summary(results)

    print(f"\nAll outputs saved to:")
    print(f"  CSV:   {CSV_PATH}")
    print(f"  Plots: {PLOTS_DIR}/")


if __name__ == '__main__':
    main()
