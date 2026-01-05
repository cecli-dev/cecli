#!/bin/bash

# FIXME - should be able to choose the keys to pass internal
#
docker run \
  -it --rm \
  --memory=12g \
  --memory-swap=12g \
  --add-host=host.docker.internal:host-gateway \
  -v $(pwd):/cecli \
  -v $(pwd)/tmp.benchmarks/.:/benchmarks \
  -e GEMINI_API_KEY=$GEMINI_API_KEY \
  -e PROMPT_COMMAND='history -a' \
  -e HISTCONTROL=ignoredups \
  -e HISTSIZE=10000 \
  -e HISTFILESIZE=20000 \
  -e AIDER_DOCKER=1 \
  -e AIDER_BENCHMARK_DIR=/benchmarks \
  cecli-cat \
  bash
