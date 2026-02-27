#!/bin/bash
echo "🧹 Cleaning up old numpy/pandas..."
pip uninstall numpy pandas -y || true

echo "📦 Installing compatible numpy first..."
pip install numpy==1.24.3

echo "📦 Installing pandas..."
pip install pandas==1.5.3

echo "📦 Installing remaining dependencies..."
pip install -r requirements.txt

echo "✅ Installation complete"
