#!/usr/bin/env python3
"""
ml_benchmark.py — Core ML workload for page-size impact study.

Four workload modes:
  model_load   — Load a large pre-trained model from disk (cold-start)
  inference    — Repeated forward passes on a loaded model (steady-state)
  tensor_alloc — Allocate and operate on very large tensors (contiguous memory stress)
  batch_vary   — Inference with different batch sizes (memory scaling)

All workloads run on CPU only (no CUDA) to isolate OS memory behavior.
Output format: RESULT: key=value key=value ...  (for parsing by analyze_results.py)

Usage:
  python3 ml_benchmark.py model_load [--num-iters N]
  python3 ml_benchmark.py inference  [--num-iters N] [--batch-size B]
  python3 ml_benchmark.py tensor_alloc [--num-iters N] [--tensor-size S]
  python3 ml_benchmark.py batch_vary [--num-iters N]
"""

import argparse
import time
import sys

import torch
import torchvision.models as models


def progress_bar(current, total, label='', bar_len=40):
    """Print a progress bar to stderr (keeps stdout clean for RESULT lines)."""
    frac = current / total
    filled = int(bar_len * frac)
    bar = '█' * filled + '░' * (bar_len - filled)
    pct = frac * 100
    print(f'\r  {label} [{bar}] {current}/{total} ({pct:.0f}%)', end='', file=sys.stderr, flush=True)
    if current == total:
        print(file=sys.stderr)  # newline at end


def get_page_config():
    """Read current THP setting to label output."""
    try:
        with open('/sys/kernel/mm/transparent_hugepage/enabled', 'r') as f:
            line = f.read().strip()
            # Format: "always [madvise] never" — bracketed is active
            if '[always]' in line:
                return '2MB'
            elif '[never]' in line:
                return '4KB'
            else:
                return 'madvise'
    except Exception:
        return 'unknown'


def workload_model_load(args):
    """Load a pre-trained model from disk. Measures cold-start allocation overhead."""
    page_config = get_page_config()

    for i in range(args.num_iters):
        progress_bar(i, args.num_iters, label='model_load')

        # Clear any cached model from previous iteration
        if i > 0:
            del model  # noqa: F821
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
            import gc; gc.collect()

        t0 = time.perf_counter()
        model = models.resnet152(weights=models.ResNet152_Weights.IMAGENET1K_V1)
        model.eval()
        load_time = time.perf_counter() - t0

        print(f"RESULT: workload=model_load page_config={page_config} "
              f"model=resnet152 load_time_sec={load_time:.6f} "
              f"inference_time_sec=0 batch_size=0 tensor_size=0 "
              f"num_iters={args.num_iters} iter={i+1}")

    progress_bar(args.num_iters, args.num_iters, label='model_load')


def workload_inference(args):
    """Repeated forward passes on a loaded model. Measures steady-state performance."""
    page_config = get_page_config()

    # Load model once
    model = models.resnet152(weights=models.ResNet152_Weights.IMAGENET1K_V1)
    model.eval()

    batch_size = args.batch_size
    # Create a random input tensor (ImageNet-sized: 3×224×224)
    dummy_input = torch.randn(batch_size, 3, 224, 224)

    # Warmup pass (not measured)
    with torch.no_grad():
        _ = model(dummy_input)

    # Timed inference loop
    times = []
    with torch.no_grad():
        for i in range(args.num_iters):
            progress_bar(i, args.num_iters, label='inference')
            t0 = time.perf_counter()
            _ = model(dummy_input)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
        progress_bar(args.num_iters, args.num_iters, label='inference')

    avg_time = sum(times) / len(times)
    total_time = sum(times)

    print(f"RESULT: workload=inference page_config={page_config} "
          f"model=resnet152 load_time_sec=0 "
          f"inference_time_sec={avg_time:.6f} "
          f"total_inference_sec={total_time:.6f} "
          f"batch_size={batch_size} tensor_size=0 "
          f"num_iters={args.num_iters} iter=0")


def workload_tensor_alloc(args):
    """Allocate and operate on large tensors. Stress-tests contiguous memory allocation."""
    page_config = get_page_config()
    tensor_size = args.tensor_size

    times = []
    for i in range(args.num_iters):
        progress_bar(i, args.num_iters, label='tensor_alloc')
        t0 = time.perf_counter()

        # Allocate a large tensor
        t = torch.randn(tensor_size, tensor_size)

        # Perform a simple operation to force memory access across the tensor
        _ = t.sum()
        _ = t.mean()
        _ = t @ t.T  # Matrix multiply — touches all memory

        elapsed = time.perf_counter() - t0
        times.append(elapsed)

        # Explicitly free to allow reallocation
        del t
        import gc; gc.collect()

    progress_bar(args.num_iters, args.num_iters, label='tensor_alloc')

    avg_time = sum(times) / len(times)
    total_time = sum(times)
    mem_mb = (tensor_size * tensor_size * 4) / (1024 * 1024)  # float32 = 4 bytes

    print(f"RESULT: workload=tensor_alloc page_config={page_config} "
          f"model=none load_time_sec=0 "
          f"inference_time_sec={avg_time:.6f} "
          f"total_inference_sec={total_time:.6f} "
          f"batch_size=0 tensor_size={tensor_size} "
          f"tensor_mem_mb={mem_mb:.1f} "
          f"num_iters={args.num_iters} iter=0")


def workload_batch_vary(args):
    """Run inference with different batch sizes to study memory scaling."""
    page_config = get_page_config()
    batch_sizes = [1, 32, 128]

    # Load model once
    model = models.resnet152(weights=models.ResNet152_Weights.IMAGENET1K_V1)
    model.eval()

    for bs in batch_sizes:
        dummy_input = torch.randn(bs, 3, 224, 224)

        # Warmup
        with torch.no_grad():
            _ = model(dummy_input)

        # Timed loop
        times = []
        with torch.no_grad():
            for i in range(args.num_iters):
                progress_bar(i, args.num_iters, label=f'batch_vary(bs={bs})')
                t0 = time.perf_counter()
                _ = model(dummy_input)
                elapsed = time.perf_counter() - t0
                times.append(elapsed)
            progress_bar(args.num_iters, args.num_iters, label=f'batch_vary(bs={bs})')

        avg_time = sum(times) / len(times)
        total_time = sum(times)

        print(f"RESULT: workload=batch_vary page_config={page_config} "
              f"model=resnet152 load_time_sec=0 "
              f"inference_time_sec={avg_time:.6f} "
              f"total_inference_sec={total_time:.6f} "
              f"batch_size={bs} tensor_size=0 "
              f"num_iters={args.num_iters} iter=0")


def main():
    parser = argparse.ArgumentParser(
        description='ML Benchmark for Page-Size Impact Study')
    parser.add_argument('workload',
                        choices=['model_load', 'inference', 'tensor_alloc', 'batch_vary'],
                        help='Workload type to run')
    parser.add_argument('--num-iters', type=int, default=10,
                        help='Number of iterations (default: 10)')
    parser.add_argument('--batch-size', type=int, default=32,
                        help='Batch size for inference workload (default: 32)')
    parser.add_argument('--tensor-size', type=int, default=10000,
                        help='Tensor dimension N for NxN allocation (default: 10000)')

    args = parser.parse_args()

    print(f"=== ML Benchmark: {args.workload} ===", file=sys.stderr)
    print(f"Page config: {get_page_config()}", file=sys.stderr)
    print(f"Device: CPU (torch {torch.__version__})", file=sys.stderr)

    workloads = {
        'model_load': workload_model_load,
        'inference': workload_inference,
        'tensor_alloc': workload_tensor_alloc,
        'batch_vary': workload_batch_vary,
    }

    workloads[args.workload](args)

    print(f"=== Done: {args.workload} ===", file=sys.stderr)


if __name__ == '__main__':
    main()
