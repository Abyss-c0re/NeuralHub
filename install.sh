#!/bin/bash
# NeuralHub - Installation script
# Supports standard install and --dev for editable NeuralCore development
# (and makes NeuralHub itself available for editable use by dependents)

set -euo pipefail

echo "=== NeuralHub Installation ==="

# Parse dev argument
DEV_MODE=false
if [[ "${1:-}" == "--dev" ]] || [[ "${1:-}" == "-d" ]] || [[ "${1:-}" == "dev" ]]; then
  DEV_MODE=true
fi

# Script directory (NeuralHub root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$DEV_MODE" = true ]; then
  echo "🚀 Dev mode activated — linking editable NeuralCore..."

  # Parent directory = project root in common layouts (ProjectNexus/...)
  PARENT_DIR="$(dirname "$SCRIPT_DIR")"
  PYPROJECT="$SCRIPT_DIR/pyproject.toml"

  # ──────────────────────────────────────────────────────────────
  # NeuralCore detection / clone (same logic as NeuralVoid)
  # ──────────────────────────────────────────────────────────────
  # 1. Parent itself is NeuralCore (rare submodule layout)
  if [ -f "$PARENT_DIR/pyproject.toml" ] && [ -d "$PARENT_DIR/src/neuralcore" ]; then
    NEURALCORE_PATH="$PARENT_DIR"
    echo "✅ Detected NeuralCore project at parent (client submodule)"

  # 2. Sibling NeuralCore folder (standard dev layout)
  elif [ -d "$PARENT_DIR/NeuralCore" ] && \
       [ -f "$PARENT_DIR/NeuralCore/pyproject.toml" ] && \
       [ -d "$PARENT_DIR/NeuralCore/src/neuralcore" ]; then
    NEURALCORE_PATH="$PARENT_DIR/NeuralCore"
    echo "✅ Detected sibling NeuralCore project at $NEURALCORE_PATH"

  else
    echo "ℹ️  No local NeuralCore found — cloning using pyproject.toml link..."
    CORE_GIT_URL=$(grep -oP 'neuralcore @ \Kgit\+https?://[^ "]+' "$PYPROJECT" 2>/dev/null | sed 's|^git+||' || echo "https://github.com/Abyss-c0re/NeuralCore.git")
    CLONE_DIR="$PARENT_DIR/NeuralCore"
    if [ ! -d "$CLONE_DIR" ]; then
      git clone "$CORE_GIT_URL" "$CLONE_DIR"
      echo "✅ Cloned NeuralCore to $CLONE_DIR"
    else
      echo "✅ Using existing NeuralCore clone at $CLONE_DIR"
    fi
    NEURALCORE_PATH="$CLONE_DIR"
  fi

  # Make NeuralCore editable
  echo "🔄 Removing existing neuralcore dependency..."
  uv remove neuralcore 2>/dev/null || true
  echo "🔗 Adding NeuralCore as editable dependency from $NEURALCORE_PATH..."
  uv add --editable "$NEURALCORE_PATH"

  echo "✅ NeuralHub is now ready for local development."
  echo "   Dependents (NeuralVoid, etc.) can also find the local NeuralHub via their own --dev scripts."
fi

# Standard installation
echo "📦 Syncing dependencies..."
uv sync

echo "🛠 Installing NeuralHub in editable mode..."
uv pip install -e .

echo ""
echo "✅ NeuralHub installation completed successfully!"
if [ "$DEV_MODE" = true ]; then
  echo "🔧 Dev mode active — edits to NeuralCore will be live immediately."
  echo "   (NeuralHub itself is also available as editable for any project that depends on it.)"
fi

echo ""
echo "Next steps:"
echo "  uv run python -c 'from neuralhub import AgentHub, NeuralHub; print(\"OK\")'"
echo "  (or uv pip install -e . from a dependent project)"
