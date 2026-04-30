#!/bin/bash
# setup_env.sh — Create Python venv and install ML dependencies
# Run this once before experiments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== ML Workload Environment Setup ==="

# Create venv
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
else
    echo "Virtual environment already exists."
fi

# Activate
source .venv/bin/activate

# Install PyTorch (CPU-only) + dependencies
echo ""
echo "Installing PyTorch (CPU-only), torchvision, matplotlib, numpy..."
pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install matplotlib numpy

# Pre-download the ResNet-152 weights so experiments measure disk→memory, not network→memory
echo ""
echo "Pre-downloading ResNet-152 pre-trained weights..."
python3 -c "
import torchvision.models as models
print('Downloading ResNet-152 weights...')
model = models.resnet152(weights=models.ResNet152_Weights.IMAGENET1K_V1)
print('ResNet-152 weights cached successfully.')
print(f'Model parameters: {sum(p.numel() for p in model.parameters()):,}')
"

echo ""
echo "=== Setup complete ==="
echo "To activate: source .venv/bin/activate"
echo "To test: python3 ml_benchmark.py model_load --num-iters 1"
