#!/bin/bash
# run_experiments.sh — Automated synthetic workload benchmarking
# Runs all access patterns × page size configs with perf stat instrumentation

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# === Configuration ===
SIZE_MB=1024        # 1 GB working set (>> 8MB L3 cache)
ITERATIONS=3        # iterations per run
REPETITIONS=3       # repeat each experiment for statistical stability
STRIDES=(4096 65536)

PERF_EVENTS="page-faults,minor-faults,major-faults,dTLB-load-misses,dTLB-store-misses,iTLB-load-misses,cycles,instructions"

RAW_DIR="$SCRIPT_DIR/raw_results"
mkdir -p "$RAW_DIR"

# === Compile ===
echo "=== Compiling load.cpp ==="
g++ -O2 -o load load.cpp
echo "Compiled successfully."

# === Helper function ===
run_one() {
    local pattern="$1"
    local page_config="$2"  # 4KB or 2MB
    local stride="${3:-1}"
    local rep="$4"

    local env_hp=0
    if [ "$page_config" = "2MB" ]; then
        env_hp=1
    fi

    local label="${pattern}_stride${stride}_${page_config}_rep${rep}"
    local logfile="$RAW_DIR/${label}.log"

    echo "  Running: $label"

    # Build command args
    local cmd_args="$SIZE_MB $ITERATIONS $pattern"
    if [ "$pattern" = "stride" ]; then
        cmd_args="$cmd_args $stride"
    fi

    # Drop caches for cold-start consistency (non-interactive sudo, skip if unavailable)
    sync
    sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || sleep 1

    # Run with perf stat
    USE_HUGEPAGES=$env_hp perf stat -e "$PERF_EVENTS" -o "$RAW_DIR/${label}_perf.txt" \
        ./load $cmd_args > "$RAW_DIR/${label}_output.txt" 2> "$RAW_DIR/${label}_stderr.txt"

    echo "    Done: $label"
}

# === Run all experiments ===
echo ""
echo "=== Running Experiments ==="
echo "Memory: ${SIZE_MB}MB | Iterations: ${ITERATIONS} | Repetitions: ${REPETITIONS}"
echo ""

# Sequential access
echo "--- Sequential Access ---"
for rep in $(seq 1 $REPETITIONS); do
    run_one "seq" "4KB" 1 "$rep"
    run_one "seq" "2MB" 1 "$rep"
done

# Random access
echo "--- Random Access ---"
for rep in $(seq 1 $REPETITIONS); do
    run_one "rand" "4KB" 1 "$rep"
    run_one "rand" "2MB" 1 "$rep"
done

# Strided access
for stride in "${STRIDES[@]}"; do
    echo "--- Strided Access (stride=${stride}) ---"
    for rep in $(seq 1 $REPETITIONS); do
        run_one "stride" "4KB" "$stride" "$rep"
        run_one "stride" "2MB" "$stride" "$rep"
    done
done

echo ""
echo "=== All experiments complete ==="
echo "Raw results saved to: $RAW_DIR/"
echo ""

# List result files
echo "Generated files:"
ls -la "$RAW_DIR/" | tail -n +2
