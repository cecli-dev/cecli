#!/bin/bash
# Benchmark runner script for testing multiple OpenRouter models
# Usage: ./run_benchmark_variations.sh [OPTIONS]

set -e  # Exit on error

# Default values
BASE_NAME="cecli-base-hashline-9"
EDIT_FORMAT="hashline"
MAP_TOKENS="512"
THREADS="1"
LANGUAGES="javascript,python,rust,go,java"
HASH_RE="^[15]"
NUM_TESTS="32"
EXERCISES_DIR="polyglot-benchmark"
OUTPUT_DIR="tmp.benchmarks"
SLEEP_BETWEEN=30  # Seconds to sleep between runs

# List of models to test
# RERUN
#    "openrouter/minimax/minimax-m2.1"
#    "openrouter/qwen/qwen3-vl-235b-a22b-thinking"
MODELS=(
    "openrouter/google/gemini-3-flash-preview"
    "openrouter/deepseek/deepseek-v3.2-exp"
#    "openrouter/moonshotai/kimi-k2.5"
#    "openrouter/openai/gpt-oss-120b"
#    "openrouter/openai/gpt-5.2"   
#    "openrouter/google/gemini-3-flash-preview"
#    "openrouter/google/gemini-3-pro-preview"
#    "openrouter/anthropic/claude-haiku-4.5"
#    "openrouter/anthropic/claude-sonnet-4.5" 
)

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --base-name)
            BASE_NAME="$2"
            shift 2
            ;;
        --edit-format)
            EDIT_FORMAT="$2"
            shift 2
            ;;
        --map-tokens)
            MAP_TOKENS="$2"
            shift 2
            ;;
        --threads)
            THREADS="$2"
            shift 2
            ;;
        --hash-re)
            HASH_RE="$2"
            shift 2
            ;;
        --num-tests)
            NUM_TESTS="$2"
            shift 2
            ;;
        --exercises-dir)
            EXERCISES_DIR="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --sleep)
            SLEEP_BETWEEN="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --base-name NAME      Base name for benchmark runs (default: $BASE_NAME)"
            echo "  --edit-format FORMAT  Edit format to use (default: $EDIT_FORMAT)"
            echo "  --map-tokens TOKENS   Map tokens (default: $MAP_TOKENS)"
            echo "  --threads N           Number of threads (default: $THREADS)"
            echo "  --hash-re REGEX       Hash regex filter (default: $HASH_RE)"
            echo "  --num-tests N         Number of tests to run (default: $NUM_TESTS)"
            echo "  --exercises-dir DIR   Exercises directory (default: $EXERCISES_DIR)"
            echo "  --output-dir DIR      Output directory (default: $OUTPUT_DIR)"
            echo "  --sleep SECONDS       Sleep between runs in seconds (default: $SLEEP_BETWEEN)"
            echo "  --help                Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 --threads 2 --num-tests 5"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Function to run a single benchmark
run_benchmark() {
    local model="$1"
    local run_name="$2"

    echo "========================================================================"
    echo "Starting benchmark: $run_name"
    echo "Model: $model"
    echo "Time: $(date)"
    echo "========================================================================"

    # Create the benchmark command
    ./benchmark/benchmark.py "$run_name" \
        --model "$model" \
        --edit-format "$EDIT_FORMAT" \
        --map-tokens "$MAP_TOKENS" \
        --threads "$THREADS" \
        --hash-re "$HASH_RE" \
        --num-tests "$NUM_TESTS" \
        --languages "$LANGUAGES" \
        --exercises-dir "$EXERCISES_DIR"

    echo "Benchmark completed: $run_name"
    echo "Results directory: $OUTPUT_DIR/$(ls -t $OUTPUT_DIR | grep "$run_name" | head -1)"
    echo ""
}

# Function to generate statistics for all completed runs
generate_stats() {
    echo "========================================================================"
    echo "Generating statistics for all completed runs"
    echo "========================================================================"

    for dir in "$OUTPUT_DIR"/*; do
        if [ -d "$dir" ] && [ -f "$dir/.cecli.results.json" ]; then
            echo "Processing: $(basename "$dir")"
            ./benchmark/benchmark.py --stats "$dir" || true
            echo ""
        fi
    done
}

# Main execution
main() {
    echo "========================================================================"
    echo "OpenRouter Model Benchmark Runner"
    echo "========================================================================"
    echo "Configuration:"
    echo "  Base name:      $BASE_NAME"
    echo "  Edit format:    $EDIT_FORMAT"
    echo "  Map tokens:     $MAP_TOKENS"
    echo "  Threads:        $THREADS"
    echo "  Hash regex:     $HASH_RE"
    echo "  Num tests:      $NUM_TESTS"
    echo "  Exercises dir:  $EXERCISES_DIR"
    echo "  Output dir:     $OUTPUT_DIR"
    echo "  Sleep between:  ${SLEEP_BETWEEN}s"
    echo "  Models to test: ${#MODELS[@]}"
    echo ""

    # Create output directory if it doesn't exist
    mkdir -p "$OUTPUT_DIR"

    # Run benchmarks for each model
    for model in "${MODELS[@]}"; do
        # Create a run name by replacing slashes with hyphens
        local model_slug=$(echo "$model" | sed 's|/|-|g')
        local run_name="${BASE_NAME}-${model_slug}"

        run_benchmark "$model" "$run_name"

        # Sleep between runs to avoid rate limiting
        if [ "$SLEEP_BETWEEN" -gt 0 ]; then
            echo "Sleeping for ${SLEEP_BETWEEN} seconds before next run..."
            sleep "$SLEEP_BETWEEN"
            echo ""
        fi
    done

    # Generate statistics
    generate_stats

    echo "========================================================================"
    echo "All benchmarks completed!"
    echo "========================================================================"
    echo ""
    echo "Summary of results directories:"
    ls -la "$OUTPUT_DIR" | grep "$BASE_NAME"
    echo ""
    echo "To view statistics for a specific run:"
    echo "  ./benchmark/benchmark.py --stats $OUTPUT_DIR/<run-directory>"
    echo ""
    echo "To compare all results:"
    echo "  for dir in $OUTPUT_DIR/*$BASE_NAME*; do"
    echo "    echo \"=== \$(basename \$dir) ===\""
    echo "    ./benchmark/benchmark.py --stats \"\$dir\" 2>/dev/null | grep -E '(pass_rate|total_cost|completed_tests)' || true"
    echo "  done"
}

# Run main function
main
