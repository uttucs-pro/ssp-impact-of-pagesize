#!/usr/bin/env python3
"""
analyze_results.py — Parse ML workload experiment results,
aggregate across repetitions, generate comparison charts and CSV.

Parses:
  - *_output.txt: RESULT lines from ml_benchmark.py
  - *_perf.txt:   perf stat output files

Generates:
  - results.csv:  Aggregated metrics (mean ± std)
  - plots/:       Comparison charts (8 charts)
"""

import os
import re
import csv
import sys
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(SCRIPT_DIR, 'raw_results')
PLOTS_DIR = os.path.join(SCRIPT_DIR, 'plots')
CSV_PATH = os.path.join(SCRIPT_DIR, 'results.csv')

os.makedirs(PLOTS_DIR, exist_ok=True)

# Color scheme (consistent with other workloads)
COLOR_4KB = '#4A90D9'
COLOR_2MB = '#E74C3C'


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
                try:
                    metrics[name] = int(val_str)
                except ValueError:
                    pass
            # Match "<not supported>" or "<not counted>" lines
            m_ns = re.match(r'^\s*<not\s+\w+>\s+(\S+)', line)
            if m_ns:
                metrics[m_ns.group(1)] = 0
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
    """Parse RESULT lines from ml_benchmark.py output.

    Returns a list of dicts (one per RESULT line) since batch_vary
    produces multiple RESULT lines.
    """
    results = []
    with open(filepath) as f:
        for line in f:
            if line.startswith('RESULT:'):
                row = {}
                for part in line.strip().split()[1:]:
                    key, val = part.split('=', 1)
                    try:
                        row[key] = float(val)
                    except ValueError:
                        row[key] = val
                results.append(row)
    return results


def discover_experiments():
    """Discover all experiment result files and group them.

    Groups by config_key (e.g., 'model_load_4KB_cold') across repetitions.
    For batch_vary, creates separate config keys per batch size.
    """
    experiments = defaultdict(list)

    for fname in sorted(os.listdir(RAW_DIR)):
        if not fname.endswith('_perf.txt'):
            continue

        label = fname.replace('_perf.txt', '')
        # Parse label: workload_PageConfig_CacheState_repN
        parts = label.rsplit('_rep', 1)
        if len(parts) != 2:
            continue
        config_key = parts[0]  # e.g., model_load_4KB_cold
        rep = int(parts[1])

        perf_file = os.path.join(RAW_DIR, fname)
        output_file = os.path.join(RAW_DIR, label + '_output.txt')

        perf_data = parse_perf_file(perf_file)
        output_results = parse_output_file(output_file) if os.path.exists(output_file) else []

        if not output_results:
            continue

        # For batch_vary, we get multiple RESULT lines (one per batch size)
        # Split them into separate config keys
        workload = output_results[0].get('workload', 'unknown')

        if workload == 'batch_vary':
            for result in output_results:
                bs = int(result.get('batch_size', 0))
                bv_key = f"{config_key}_bs{bs}"
                data = {**perf_data, **result}
                data['rep'] = rep
                data['config_key'] = bv_key
                experiments[bv_key].append(data)
        else:
            # For other workloads, use the last (or only) RESULT line
            # model_load may have multiple lines (one per iter), average them
            if workload == 'model_load':
                avg_load_time = np.mean([r.get('load_time_sec', 0) for r in output_results])
                merged = {**output_results[-1], 'load_time_sec': avg_load_time}
            else:
                merged = output_results[-1] if output_results else {}

            data = {**perf_data, **merged}
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
        'cycles', 'instructions', 'wall_time_sec', 'IPC',
        'load_time_sec', 'inference_time_sec', 'total_inference_sec',
        'tensor_mem_mb',
    ]

    for config_key, reps in sorted(experiments.items()):
        row = {'config': config_key}

        # Parse config key: workload_PageConfig_CacheState[_bsN]
        # Examples: model_load_4KB_cold, batch_vary_2MB_warm_bs32
        parts = config_key.split('_')

        # Workload is the first one or two parts (model_load, tensor_alloc, batch_vary)
        # Page config is 4KB or 2MB
        # Find page config position
        page_idx = None
        for i, p in enumerate(parts):
            if p in ('4KB', '2MB'):
                page_idx = i
                break

        if page_idx is None:
            continue

        row['workload'] = '_'.join(parts[:page_idx])
        row['page_config'] = parts[page_idx]
        row['cache_state'] = parts[page_idx + 1] if page_idx + 1 < len(parts) else 'unknown'

        # Check for batch size suffix
        row['batch_size'] = 0
        for p in parts:
            if p.startswith('bs'):
                try:
                    row['batch_size'] = int(p[2:])
                except ValueError:
                    pass

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
        print("WARNING: No results to save.")
        return
    keys = results[0].keys()
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(results)
    print(f"Saved CSV: {path}")


def get_display_label(row):
    """Create a readable label for a config."""
    workload = row.get('workload', '')
    cache = row.get('cache_state', '')
    bs = row.get('batch_size', 0)

    label = workload.replace('_', ' ').title()

    if bs and bs > 0:
        label += f"\n(bs={bs})"

    if cache:
        label += f"\n{cache}"

    return label


def get_short_label(row):
    """Short label for tight charts."""
    workload = row.get('workload', '')
    cache = row.get('cache_state', '')
    bs = row.get('batch_size', 0)
    parts = [workload.replace('_', ' ')]
    if bs and bs > 0:
        parts.append(f"bs{bs}")
    parts.append(cache)
    return '\n'.join(parts)


def create_charts(results):
    """Generate comparison charts."""
    # Separate results by workload type for different charts
    model_load = [r for r in results if r['workload'] == 'model_load']
    inference = [r for r in results if r['workload'] == 'inference']
    tensor_alloc = [r for r in results if r['workload'] == 'tensor_alloc']
    batch_vary = [r for r in results if r['workload'] == 'batch_vary']

    # === Chart 1: Model Load Time ===
    _bar_chart_by_config(
        model_load,
        metric='load_time_sec',
        ylabel='Load Time (seconds)',
        title='Model Load Time: 4 KB vs 2 MB Pages',
        filename='model_load_time.png',
        log_scale=False,
    )

    # === Chart 2: Inference Latency ===
    inf_data = inference + batch_vary
    if inf_data:
        _bar_chart_by_config(
            inf_data,
            metric='inference_time_sec',
            ylabel='Inference Latency per Iteration (seconds)',
            title='Inference Latency: 4 KB vs 2 MB Pages',
            filename='inference_latency.png',
            log_scale=False,
        )

    # === Chart 3: Page Faults (all workloads) ===
    _bar_chart_by_config(
        results,
        metric='page-faults',
        ylabel='Page Faults (count)',
        title='Page Faults: 4 KB vs 2 MB Pages',
        filename='page_faults.png',
        log_scale=True,
    )

    # === Chart 4: dTLB Load Misses ===
    _bar_chart_by_config(
        results,
        metric='dTLB-load-misses',
        ylabel='dTLB Load Misses (count)',
        title='dTLB Load Misses: 4 KB vs 2 MB Pages',
        filename='dtlb_load_misses.png',
        log_scale=True,
    )

    # === Chart 5: dTLB Store Misses ===
    _bar_chart_by_config(
        results,
        metric='dTLB-store-misses',
        ylabel='dTLB Store Misses (count)',
        title='dTLB Store Misses: 4 KB vs 2 MB Pages',
        filename='dtlb_store_misses.png',
        log_scale=True,
    )

    # === Chart 6: CPU Cycles ===
    _bar_chart_by_config(
        results,
        metric='cycles',
        ylabel='CPU Cycles',
        title='CPU Cycles: 4 KB vs 2 MB Pages',
        filename='cpu_cycles.png',
        log_scale=True,
    )

    # === Chart 7: IPC ===
    _bar_chart_by_config(
        results,
        metric='IPC',
        ylabel='Instructions Per Cycle (IPC)',
        title='IPC: 4 KB vs 2 MB Pages',
        filename='ipc.png',
        log_scale=False,
    )

    # === Chart 8: Improvement Summary ===
    _improvement_summary(results)


def _bar_chart_by_config(data, metric, ylabel, title, filename, log_scale=False):
    """Create a grouped bar chart comparing 4KB vs 2MB for a given metric."""
    if not data:
        return

    # Group by display label, keep only pairs (4KB and 2MB)
    groups = {}
    for r in data:
        key = (r['workload'], r['cache_state'], r.get('batch_size', 0))
        groups.setdefault(key, {})[r['page_config']] = r

    # Filter to groups that have at least one config
    ordered_keys = sorted(groups.keys())
    labels = []
    vals_4kb = []
    vals_2mb = []
    errs_4kb = []
    errs_2mb = []

    for key in ordered_keys:
        g = groups[key]
        workload, cache, bs = key
        label_parts = [workload.replace('_', ' ')]
        if bs and bs > 0:
            label_parts.append(f"bs{bs}")
        label_parts.append(cache)
        labels.append('\n'.join(label_parts))

        r4 = g.get('4KB', {})
        r2 = g.get('2MB', {})
        vals_4kb.append(r4.get(f'{metric}_mean', 0))
        vals_2mb.append(r2.get(f'{metric}_mean', 0))
        errs_4kb.append(r4.get(f'{metric}_std', 0))
        errs_2mb.append(r2.get(f'{metric}_std', 0))

    if not labels:
        return

    fig, ax = plt.subplots(figsize=(max(12, len(labels) * 1.5), 7))
    x = np.arange(len(labels))
    width = 0.35

    ax.bar(x - width/2, vals_4kb, width, label='4 KB pages', color=COLOR_4KB,
           yerr=errs_4kb, capsize=4)
    ax.bar(x + width/2, vals_2mb, width, label='2 MB pages', color=COLOR_2MB,
           yerr=errs_2mb, capsize=4)

    ax.set_xlabel('Workload Configuration', fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9, ha='center')
    ax.legend(fontsize=11)
    if log_scale:
        # Only use log scale if max value is significantly larger than min
        all_vals = [v for v in vals_4kb + vals_2mb if v > 0]
        if all_vals and max(all_vals) / max(min(all_vals), 1) > 10:
            ax.set_yscale('log')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, filename), dpi=150)
    plt.close()
    print(f"Generated: {filename}")


def _improvement_summary(results):
    """Create improvement summary chart (% reduction in page faults + dTLB misses)."""
    # Group by (workload, cache_state, batch_size)
    groups = {}
    for r in results:
        key = (r['workload'], r['cache_state'], r.get('batch_size', 0))
        groups.setdefault(key, {})[r['page_config']] = r

    # Only include groups with both 4KB and 2MB data
    labels = []
    pf_reductions = []
    tlb_reductions = []

    for key in sorted(groups.keys()):
        g = groups[key]
        if '4KB' not in g or '2MB' not in g:
            continue

        workload, cache, bs = key
        label_parts = [workload.replace('_', ' ')]
        if bs and bs > 0:
            label_parts.append(f"bs{bs}")
        label_parts.append(cache)
        labels.append('\n'.join(label_parts))

        v4_pf = g['4KB'].get('page-faults_mean', 1)
        v2_pf = g['2MB'].get('page-faults_mean', 1)
        pf_pct = (v4_pf - v2_pf) / v4_pf * 100 if v4_pf > 0 else 0
        pf_reductions.append(pf_pct)

        v4_tlb = g['4KB'].get('dTLB-load-misses_mean', 1)
        v2_tlb = g['2MB'].get('dTLB-load-misses_mean', 1)
        tlb_pct = (v4_tlb - v2_tlb) / v4_tlb * 100 if v4_tlb > 0 else 0
        tlb_reductions.append(tlb_pct)

    if not labels:
        print("WARNING: No paired results for improvement summary.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(max(14, len(labels) * 1.5), 7))

    # Page fault reduction
    ax = axes[0]
    colors = ['#2ECC71' if v >= 0 else '#E74C3C' for v in pf_reductions]
    bars = ax.bar(range(len(labels)), pf_reductions, color=colors,
                  edgecolor=['#27AE60' if v >= 0 else '#C0392B' for v in pf_reductions],
                  linewidth=1.5)
    ax.set_ylabel('Reduction (%)', fontsize=12)
    ax.set_title('Page Fault Reduction\n(4KB → 2MB)', fontsize=13, fontweight='bold')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8, ha='center')
    for bar, val in zip(bars, pf_reductions):
        ypos = bar.get_height() + 1 if val >= 0 else bar.get_height() - 3
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)

    # dTLB load miss reduction
    ax = axes[1]
    colors = ['#3498DB' if v >= 0 else '#E74C3C' for v in tlb_reductions]
    bars = ax.bar(range(len(labels)), tlb_reductions, color=colors,
                  edgecolor=['#2980B9' if v >= 0 else '#C0392B' for v in tlb_reductions],
                  linewidth=1.5)
    ax.set_ylabel('Reduction (%)', fontsize=12)
    ax.set_title('dTLB Load Miss Reduction\n(4KB → 2MB)', fontsize=13, fontweight='bold')
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8, ha='center')
    for bar, val in zip(bars, tlb_reductions):
        ypos = bar.get_height() + 1 if val >= 0 else bar.get_height() - 3
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=0, color='black', linewidth=0.5)

    plt.tight_layout()
    plt.savefig(os.path.join(PLOTS_DIR, 'improvement_summary.png'), dpi=150)
    plt.close()
    print("Generated: improvement_summary.png")


def print_summary(results):
    """Print a summary table to stdout."""
    print("\n" + "=" * 120)
    print("ML WORKLOAD RESULTS SUMMARY")
    print("=" * 120)
    fmt = "{:<30} {:>12} {:>15} {:>15} {:>18} {:>10} {:>10}"
    print(fmt.format("Config", "Load Time(s)", "Infer Time(s)",
                     "Page Faults", "dTLB-Load-Miss", "IPC", "Wall(s)"))
    print("-" * 120)
    for r in results:
        label = r['config']
        print(fmt.format(
            label,
            f"{r['load_time_sec_mean']:.3f}" if r['load_time_sec_mean'] > 0 else "-",
            f"{r['inference_time_sec_mean']:.4f}" if r['inference_time_sec_mean'] > 0 else "-",
            f"{r['page-faults_mean']:,.0f} ±{r['page-faults_std']:,.0f}",
            f"{r['dTLB-load-misses_mean']:,.0f}",
            f"{r['IPC_mean']:.2f}" if r['IPC_mean'] > 0 else "-",
            f"{r['wall_time_sec_mean']:.2f}" if r['wall_time_sec_mean'] > 0 else "-",
        ))
    print("=" * 120)


def main():
    print("=== ML Workload Results Analysis ===")
    print(f"Looking for raw results in: {RAW_DIR}")

    if not os.path.isdir(RAW_DIR):
        print(f"ERROR: {RAW_DIR} does not exist. Run experiments first.")
        sys.exit(1)

    print("\nDiscovering experiments...")
    experiments = discover_experiments()
    print(f"Found {len(experiments)} configurations, "
          f"{sum(len(v) for v in experiments.values())} total runs")

    if not experiments:
        print("ERROR: No experiment results found.")
        sys.exit(1)

    print("\nAggregating results...")
    results = aggregate(experiments)

    print("\nSaving CSV...")
    save_csv(results, CSV_PATH)

    print("\nGenerating charts...")
    create_charts(results)

    print_summary(results)

    print(f"\nAll outputs saved to:")
    print(f"  CSV:   {CSV_PATH}")
    print(f"  Plots: {PLOTS_DIR}/")


if __name__ == '__main__':
    main()
