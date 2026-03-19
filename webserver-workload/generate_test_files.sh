#!/bin/bash
# generate_test_files.sh — Create test data for nginx benchmarking
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/test_data"

echo "=== Generating test data ==="

# Small files directory
SMALL_DIR="$DATA_DIR/small"
mkdir -p "$SMALL_DIR"

echo "Creating small files (1-10 KB)..."
for i in $(seq 1 500); do
    # ~5KB HTML files
    dd if=/dev/urandom bs=5120 count=1 2>/dev/null | base64 > "$SMALL_DIR/file_${i}.html"
done
echo "  Created 500 small files (~5KB each)"

# Large files directory
LARGE_DIR="$DATA_DIR/large"
mkdir -p "$LARGE_DIR"

echo "Creating large files (50 MB)..."
for i in $(seq 1 10); do
    dd if=/dev/urandom of="$LARGE_DIR/file_${i}.bin" bs=1M count=50 2>/dev/null
done
echo "  Created 10 large files (50MB each)"

echo ""
echo "=== Test data summary ==="
echo "Small files: $(ls "$SMALL_DIR" | wc -l) files, total $(du -sh "$SMALL_DIR" | cut -f1)"
echo "Large files: $(ls "$LARGE_DIR" | wc -l) files, total $(du -sh "$LARGE_DIR" | cut -f1)"
echo "Total: $(du -sh "$DATA_DIR" | cut -f1)"
