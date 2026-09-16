#!/bin/bash
# HERMES_LOCAL_STT_COMMAND target: hits the whisper service (/srv/whisper, crt#319)
# instead of shelling out to a local whisper CLI. Called as:
#   whisper_stt.sh <input_path> <output_dir> <language>
set -euo pipefail

INPUT_PATH="$1"
OUTPUT_DIR="$2"
LANGUAGE="$3"

RESAMPLED="${OUTPUT_DIR}/resampled-16k.wav"
ffmpeg -y -loglevel error -i "$INPUT_PATH" -ar 16000 -ac 1 -c:a pcm_s16le "$RESAMPLED"

# The tailnet address, not loopback: whisper is no longer in this container's
# network namespace, and it is the same URL potato posts to.
WHISPER_URL="${WHISPER_URL:-http://100.107.253.56:8090}"
RESPONSE=$(curl -sf -X POST "${WHISPER_URL}/inference" \
  -F "file=@${RESAMPLED}" \
  -F "response_format=json" \
  -F "language=${LANGUAGE}")

python3 -c "import sys, json; print(json.loads(sys.argv[1])['text'].strip())" "$RESPONSE" > "${OUTPUT_DIR}/transcript.txt"
