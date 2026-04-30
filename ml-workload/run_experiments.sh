#!/bin/bash
# run_experiments.sh — Automated ML workload benchmarking with perf stat
# Runs all workload × page_config × cache_state combinations
#
# Usage: sudo bash run_experiments.sh
# Prerequisites: Run setup_env.sh first to create venv and download model weights

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# === Configuration ===
REPETITIONS=3
PYTHON="$SCRIPT_DIR/.venv/bin/python3"

# Workload-specific iteration counts
MODEL_LOAD_ITERS=5        # model loading is slow (~2-4s per load)
INFERENCE_ITERS=100       # forward passes (fast per iteration)
TENSOR_ALLOC_ITERS=50     # tensor allocation + matmul
BATCH_VARY_ITERS=50       # per batch size

INFERENCE_BATCH=32
TENSOR_SIZE=10000          # 10000×10000 float32 = ~400 MB

PERF_EVENTS="page-faults,minor-faults,major-faults,dTLB-load-misses,dTLB-store-misses,iTLB-load-misses,cycles,instructions"

RAW_DIR="$SCRIPT_DIR/raw_results"
mkdir -p "$RAW_DIR"

# === Verify prerequisites ===
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: Python venv not found. Run 'bash setup_env.sh' first."
    exit 1
fi

if ! command -v perf &> /dev/null; then
    echo "ERROR: perf is not installed."
    exit 1
fi

# === Helper functions ===

set_thp() {
    local mode="$1"
    echo "$mode" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null
    echo "  THP set to: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
}

drop_caches() {
    sync
    sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
}

run_one() {
    local workload="$1"     # model_load, inference, tensor_alloc, batch_vary
    local page_config="$2"  # 4KB or 2MB
    local cache_state="$3"  # cold or warm
    local rep="$4"

    local label="${workload}_${page_config}_${cache_state}_rep${rep}"

    # Skip if already done
    if [ -f "$RAW_DIR/${label}_output.txt" ]; then
        echo "  SKIP (exists): $label"
        return
    fi

    echo "  Running: $label"

    # Determine workload args
    local bench_args=""
    case "$workload" in
        model_load)
            bench_args="model_load --num-iters $MODEL_LOAD_ITERS"
            ;;
        inference)
            bench_args="inference --num-iters $INFERENCE_ITERS --batch-size $INFERENCE_BATCH"
            ;;
        tensor_alloc)
            bench_args="tensor_alloc --num-iters $TENSOR_ALLOC_ITERS --tensor-size $TENSOR_SIZE"
            ;;
        batch_vary)
            bench_args="batch_vary --num-iters $BATCH_VARY_ITERS"
            ;;
    esac

    # Cold: drop caches before each run
    if [ "$cache_state" = "cold" ]; then
        drop_caches
    fi

    # Warm: on first rep, do a quick warmup to load model into page cache
    if [ "$cache_state" = "warm" ] && [ "$rep" = "1" ]; then
        echo "    Warming up (loading model into cache)..."
        $PYTHON ml_benchmark.py model_load --num-iters 1 > /dev/null 2>&1
        sleep 1
    fi

    # Run with perf stat wrapping the entire Python process
    perf stat -e "$PERF_EVENTS" -o "$RAW_DIR/${label}_perf.txt" \
        $PYTHON ml_benchmark.py $bench_args \
        > "$RAW_DIR/${label}_output.txt" 2> "$RAW_DIR/${label}_stderr.txt"

    echo "    Done: $label"
}

# === Main ===
echo "=== ML Workload Experiments ==="
echo "Repetitions: $REPETITIONS"
echo "Workloads: model_load (${MODEL_LOAD_ITERS} iters), inference (${INFERENCE_ITERS} iters, batch=${INFERENCE_BATCH}), tensor_alloc (${TENSOR_ALLOC_ITERS} iters, size=${TENSOR_SIZE}), batch_vary (${BATCH_VARY_ITERS} iters)"
echo ""

for page_config in "4KB" "2MB"; do
    if [ "$page_config" = "4KB" ]; then
        echo "--- Setting THP to 'never' (4KB pages) ---"
        set_thp "never"
    else
        echo "--- Setting THP to 'always' (2MB huge pages) ---"
        set_thp "always"
    fi

    for workload in "model_load" "inference" "tensor_alloc" "batch_vary"; do
        for cache_state in "cold" "warm"; do
            echo ""
            echo "=== ${workload} | ${page_config} | ${cache_state} ==="
            for rep in $(seq 1 $REPETITIONS); do
                run_one "$workload" "$page_config" "$cache_state" "$rep"
            done
        done
    done
done

# Restore THP
echo ""
echo "--- Restoring THP to 'madvise' ---"
set_thp "madvise"

echo ""
echo "=== All experiments complete ==="
echo "Raw results saved to: $RAW_DIR/"
echo ""
echo "Result files:"
ls "$RAW_DIR/" | wc -l
echo " files total"
