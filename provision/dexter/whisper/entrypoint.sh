#!/bin/sh
# Fetch-and-verify the model, then exec the server. Provenance of MODEL_SHA256
# and why the model is not baked in: see the Dockerfile.
set -eu

MODEL_SHA256=a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_NAME}"
MODEL_PATH="${MODEL_DIR}/${MODEL_NAME}"

verify() { echo "${MODEL_SHA256}  ${MODEL_PATH}" | sha256sum -c - >/dev/null 2>&1; }

if [ ! -f "$MODEL_PATH" ] || ! verify; then
  [ -f "$MODEL_PATH" ] && echo "whisper: checksum mismatch, refetching" >&2
  echo "whisper: fetching ${MODEL_NAME} (141 MiB)" >&2
  mkdir -p "$MODEL_DIR"
  # Hugging Face resets this transfer mid-stream often enough to have done it
  # twice on the first real cold start, so: resume, retry on ANY error, and land
  # on the final name only once the hash matches.
  curl -fL -sS --retry 5 --retry-all-errors --retry-delay 3 -C - \
    -o "${MODEL_PATH}.part" "$MODEL_URL"
  mv "${MODEL_PATH}.part" "$MODEL_PATH"
  verify || { echo "whisper: FATAL checksum mismatch after fetch" >&2; exit 1; }
  echo "whisper: model verified" >&2
fi

exec /usr/local/bin/whisper-server \
  -m "$MODEL_PATH" --host "$WHISPER_HOST" --port "$WHISPER_PORT" "$@"
