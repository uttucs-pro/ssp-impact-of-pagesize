#!/bin/bash
# run_experiments.sh — Automated nginx + wrk benchmarking with perf stat
# Runs all file_size × concurrency × page_config × cache_state combinations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# === Configuration ===
NGINX_CONF="$SCRIPT_DIR/nginx.conf"
BASE_URL="http://127.0.0.1:8088"
WRK_DURATION=30            # seconds per wrk run
WRK_THREADS=4              # wrk threads
REPETITIONS=3

# Concurrency levels
CONCURRENCY_LOW=10
CONCURRENCY_HIGH=200

# wrk URLs — pick a representative file for each category
SMALL_URL="$BASE_URL/small/file_1.html"
LARGE_URL="$BASE_URL/large/file_1.bin"

# For small files: use a lua script to request random files
# For large files: single file is fine (50MB sequential read)

PERF_EVENTS="page-faults,minor-faults,major-faults,dTLB-load-misses,dTLB-store-misses,iTLB-load-misses,cycles,instructions"

RAW_DIR="$SCRIPT_DIR/raw_results"
mkdir -p "$RAW_DIR"

# === Wrk Lua script for random small file selection ===
cat > /tmp/random_small.lua << 'LUAEOF'
counter = 0
request = function()
    counter = counter + 1
    local file_num = (counter % 500) + 1
    return wrk.format("GET", "/small/file_" .. file_num .. ".html")
end
LUAEOF

# === Helper functions ===

start_nginx() {
    sudo killall nginx 2>/dev/null || true
    sleep 1
    sudo nginx -c "$NGINX_CONF" 2>/dev/null
    sleep 1
    # Verify it's running
    if ! curl -s -o /dev/null -w '' "$BASE_URL/small/file_1.html" 2>/dev/null; then
        echo "ERROR: nginx failed to start"
        exit 1
    fi
}

stop_nginx() {
    sudo killall nginx 2>/dev/null || true
    sleep 1
}

get_nginx_master_pid() {
    cat /tmp/nginx_bench.pid 2>/dev/null || pgrep -f "nginx: master" | head -1
}

set_thp() {
    local mode="$1"  # "always" or "never"
    echo "$mode" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null
    echo "  THP set to: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
}

drop_caches() {
    sync
    sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
}

run_one() {
    local file_size="$1"     # small or large
    local concurrency="$2"    # 10 or 200
    local page_config="$3"   # 4KB or 2MB
    local cache_state="$4"   # cold or warm
    local rep="$5"

    local label="${file_size}_c${concurrency}_${page_config}_${cache_state}_rep${rep}"
    echo "  Running: $label"

    # Cold cache: drop caches and restart nginx
    if [ "$cache_state" = "cold" ]; then
        stop_nginx
        drop_caches
        start_nginx
    fi

    # For warm cache: do a quick warmup run first
    if [ "$cache_state" = "warm" ] && [ "$rep" = "1" ]; then
        echo "    Warming up cache..."
        if [ "$file_size" = "small" ]; then
            wrk -t2 -c10 -d5s -s /tmp/random_small.lua "$BASE_URL" > /dev/null 2>&1
        else
            wrk -t2 -c10 -d5s "$LARGE_URL" > /dev/null 2>&1
        fi
        sleep 1
    fi

    # Determine wrk target
    local wrk_url="$SMALL_URL"
    local wrk_extra=""
    if [ "$file_size" = "small" ]; then
        wrk_extra="-s /tmp/random_small.lua"
        wrk_url="$BASE_URL"
    else
        wrk_url="$LARGE_URL"
    fi

    # Get nginx master PID for perf
    local nginx_pid
    nginx_pid=$(get_nginx_master_pid)

    # Get all nginx worker PIDs
    local worker_pids
    worker_pids=$(pgrep -P "$nginx_pid" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    
    if [ -z "$worker_pids" ]; then
        worker_pids="$nginx_pid"
    fi

    # Start perf stat on nginx workers in background
    sudo perf stat -e "$PERF_EVENTS" -p "$worker_pids" \
        -o "$RAW_DIR/${label}_perf.txt" &
    local perf_pid=$!
    sleep 0.5

    # Run wrk
    if [ "$file_size" = "small" ]; then
        wrk -t"$WRK_THREADS" -c"$concurrency" -d"${WRK_DURATION}s" \
            --latency -s /tmp/random_small.lua "$BASE_URL" \
            > "$RAW_DIR/${label}_wrk.txt" 2>&1
    else
        wrk -t"$WRK_THREADS" -c"$concurrency" -d"${WRK_DURATION}s" \
            --latency "$LARGE_URL" \
            > "$RAW_DIR/${label}_wrk.txt" 2>&1
    fi

    # Stop perf stat
    sleep 1
    sudo kill -INT "$perf_pid" 2>/dev/null || true
    wait "$perf_pid" 2>/dev/null || true

    echo "    Done: $label"
}

# === Main ===
echo "=== Web Server Workload Experiments ==="
echo "Duration: ${WRK_DURATION}s | Threads: ${WRK_THREADS} | Repetitions: ${REPETITIONS}"
echo ""

# Run for each page configuration
for page_config in "4KB" "2MB"; do
    if [ "$page_config" = "4KB" ]; then
        echo "--- Setting THP to 'never' (4KB pages) ---"
        set_thp "never"
    else
        echo "--- Setting THP to 'always' (2MB huge pages) ---"
        set_thp "always"
    fi

    # Restart nginx under new THP setting
    stop_nginx
    drop_caches
    start_nginx

    for file_size in "small" "large"; do
        for concurrency in "$CONCURRENCY_LOW" "$CONCURRENCY_HIGH"; do
            for cache_state in "cold" "warm"; do
                echo ""
                echo "=== ${file_size} files | concurrency=${concurrency} | ${page_config} | ${cache_state} ==="
                for rep in $(seq 1 $REPETITIONS); do
                    run_one "$file_size" "$concurrency" "$page_config" "$cache_state" "$rep"
                done
            done
        done
    done
done

# Restore THP to madvise
echo ""
echo "--- Restoring THP to 'madvise' ---"
set_thp "madvise"
stop_nginx

echo ""
echo "=== All experiments complete ==="
echo "Raw results saved to: $RAW_DIR/"
echo ""
echo "Generated files:"
ls "$RAW_DIR/" | wc -l
echo "total files in raw_results/"
