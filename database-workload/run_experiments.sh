#!/bin/bash
# run_experiments.sh — Automated PostgreSQL + sysbench benchmarking with perf stat
# Runs all workload × page_config × cache_state combinations

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# === Configuration ===
DB_NAME="spe_bench"
DB_USER="uttu"
DB_PASS="bench"
DB_HOST="localhost"
DB_PORT="5432"

SB_TABLES=4
SB_TABLE_SIZE=1000000
SB_THREADS=4
SB_DURATION=60       # seconds per run
SB_REPORT=10         # report interval

REPETITIONS=3

PERF_EVENTS="page-faults,minor-faults,major-faults,dTLB-load-misses,dTLB-store-misses,iTLB-load-misses,cycles,instructions"

RAW_DIR="$SCRIPT_DIR/raw_results"
mkdir -p "$RAW_DIR"

# Common sysbench args
SB_COMMON="--db-driver=pgsql --pgsql-host=$DB_HOST --pgsql-port=$DB_PORT --pgsql-user=$DB_USER --pgsql-password=$DB_PASS --pgsql-db=$DB_NAME --tables=$SB_TABLES --table-size=$SB_TABLE_SIZE --threads=$SB_THREADS --time=$SB_DURATION --report-interval=$SB_REPORT"

# === Helper functions ===

set_thp() {
    local mode="$1"
    echo "$mode" | sudo tee /sys/kernel/mm/transparent_hugepage/enabled > /dev/null
    echo "  THP set to: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
}

restart_postgres() {
    sudo systemctl restart postgresql
    sleep 3
    # Wait for PG to be ready
    for i in $(seq 1 10); do
        if pg_isready -h "$DB_HOST" -p "$DB_PORT" -q 2>/dev/null; then
            return 0
        fi
        sleep 1
    done
    echo "ERROR: PostgreSQL failed to start"
    exit 1
}

drop_caches() {
    sync
    sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
}

get_pg_pids() {
    # Get all PostgreSQL backend process IDs
    pgrep -f "postgres:" | tr '\n' ',' | sed 's/,$//'
}

run_one() {
    local workload="$1"     # read_only, read_write, range
    local page_config="$2"  # 4KB or 2MB
    local cache_state="$3"  # cold or warm
    local rep="$4"

    local label="${workload}_${page_config}_${cache_state}_rep${rep}"

    # Skip if already done
    if [ -f "$RAW_DIR/${label}_sysbench.txt" ]; then
        echo "  SKIP (exists): $label"
        return
    fi

    echo "  Running: $label"

    # Cold: drop caches + restart PG
    if [ "$cache_state" = "cold" ]; then
        drop_caches
        restart_postgres
    fi

    # Warm: do a quick warmup on first rep
    if [ "$cache_state" = "warm" ] && [ "$rep" = "1" ]; then
        echo "    Warming up..."
        sysbench oltp_read_only $SB_COMMON --time=10 run > /dev/null 2>&1
        sleep 1
    fi

    # Determine sysbench test
    local sb_test="oltp_read_only"
    local sb_extra=""
    case "$workload" in
        read_only)   sb_test="oltp_read_only" ;;
        read_write)  sb_test="oltp_read_write" ;;
        range)       sb_test="oltp_read_only"; sb_extra="--range_size=100 --point_selects=0 --simple_ranges=1 --sum_ranges=0 --order_ranges=0 --distinct_ranges=0" ;;
    esac

    # Get PG PIDs for perf
    local pg_pids
    pg_pids=$(get_pg_pids)

    if [ -z "$pg_pids" ]; then
        echo "    WARNING: No PostgreSQL PIDs found, skipping perf"
        # Run sysbench without perf
        sysbench "$sb_test" $SB_COMMON $sb_extra run \
            > "$RAW_DIR/${label}_sysbench.txt" 2>&1
    else
        # Start perf stat on PG backends
        sudo perf stat -e "$PERF_EVENTS" -p "$pg_pids" \
            -o "$RAW_DIR/${label}_perf.txt" &
        local perf_pid=$!
        sleep 0.5

        # Run sysbench
        sysbench "$sb_test" $SB_COMMON $sb_extra run \
            > "$RAW_DIR/${label}_sysbench.txt" 2>&1

        # Stop perf
        sleep 1
        sudo kill -INT "$perf_pid" 2>/dev/null || true
        wait "$perf_pid" 2>/dev/null || true
    fi

    echo "    Done: $label"
}

# === Main ===
echo "=== Database Workload Experiments ==="
echo "Duration: ${SB_DURATION}s | Threads: ${SB_THREADS} | Tables: ${SB_TABLES} × ${SB_TABLE_SIZE} rows | Reps: ${REPETITIONS}"
echo ""

for page_config in "4KB" "2MB"; do
    if [ "$page_config" = "4KB" ]; then
        echo "--- Setting THP to 'never' (4KB pages) ---"
        set_thp "never"
    else
        echo "--- Setting THP to 'always' (2MB huge pages) ---"
        set_thp "always"
    fi

    # Restart PG under new THP
    restart_postgres

    for workload in "read_only" "read_write" "range"; do
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
ls "$RAW_DIR/" | grep -c sysbench
echo " sysbench result files total"
