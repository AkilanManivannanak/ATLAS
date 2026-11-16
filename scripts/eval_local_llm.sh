#!/usr/bin/env bash
# Score a real language model on the ATLAS agent tasks, using a local Ollama server.
#   1. Install Ollama (https://ollama.com) and start it.
#   2. ./scripts/eval_local_llm.sh            # default model: llama3.1 (tool calling required)
#      ./scripts/eval_local_llm.sh qwen2.5:7b
# Results are written to results/agent_evals.json with the model's row added; commit that file to publish them.
set -euo pipefail
MODEL="${1:-llama3.1}"
cd "$(dirname "$0")/.."
command -v ollama >/dev/null || { echo "Ollama is not installed: https://ollama.com"; exit 1; }
ollama pull "$MODEL"
export ATLAS_LLM_BASE_URL="${ATLAS_LLM_BASE_URL:-http://localhost:11434/v1}" ATLAS_LLM_MODEL="$MODEL"
PYTHONPATH=src python -m atlas.agent.evals --llm --out results/agent_evals.json
