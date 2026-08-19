#!/bin/bash
# HERMES_LOCAL_STT_COMMAND target: hits the shared whisper-server (127.0.0.1:8090)
# instead of shelling out to a local whisper CLI. Called as:
#   whisper_stt.sh <input_path> <output_dir> <language>
set -euo pipefail

INPUT_PATH="$1"
OUTPUT_DIR="$2"
LANGUAGE="$3"

RESAMPLED="${OUTPUT_DIR}/resampled-16k.wav"
ffmpeg -y -loglevel error -i "$INPUT_PATH" -ar 16000 -ac 1 -c:a pcm_s16le "$RESAMPLED"

RESPONSE=$(curl -sf -X POST http://127.0.0.1:8090/inference \
  -F "file=@${RESAMPLED}" \
  -F "response_format=json" \
  -F "language=${LANGUAGE}")

python3 -c "import sys, json; print(json.loads(sys.argv[1])['text'].strip())" "$RESPONSE" > "${OUTPUT_DIR}/transcript.txt"
