# whisper.cpp STT server -- the service whose absence made every voice note fail
# for three weeks. It answers POST /inference on :8090, the endpoint that
# ../zaxon/relay/bin/whisper_stt.sh has always called.
#
# WHY THIS IS A BUILD AND NOT A LIFT. The dead original was /usr/bin/whisper-server
# inside the Stopped `hermes` WSL distro, dynamically linked against
# libwhisper.so.1; carried out of that rootfs it does not start at all. So the
# binary is rebuilt from a pinned upstream tag, and only the MODEL was worth
# recovering -- and even that turned out to be stock, see the checksum below.
#
# THE SERVICE BLOCK IS IN ../zaxon/compose.yaml, not here. whisper_stt.sh curls
# 127.0.0.1:8090 from INSIDE the gateway container, so whisper has to share the
# gateway's network namespace; a second compose project could only reach it with
# network_mode: "container:zaxon-gateway", which compose cannot order and which
# breaks whenever the gateway is recreated.
FROM debian:bookworm-slim AS build
ARG WHISPER_VERSION=v1.9.3
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${WHISPER_VERSION}" \
      https://github.com/ggerganov/whisper.cpp /src
WORKDIR /src
# BUILD_SHARED_LIBS=OFF folds libwhisper and libggml into the executable, so the
# runtime stage copies exactly one file and cannot repeat the dangling-.so
# failure that made the distro's own binary unusable.
RUN cmake -B build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=OFF \
      -DWHISPER_BUILD_TESTS=OFF \
 && cmake --build build -j "$(nproc)" --target whisper-server

FROM debian:bookworm-slim
# curl is not a convenience: entrypoint.sh fetches the model with it, and the
# compose healthcheck is a curl against /health.
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/whisper-server /usr/local/bin/whisper-server
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# THE MODEL IS NOT BAKED IN. ggml-base.en.bin is 141 MiB -- larger than the rest
# of this image together -- and it never changes, so it lives on a volume that
# survives every image pull. entrypoint.sh fetches it on first start and refuses
# to serve anything with the wrong SHA256.
#
# WHERE THAT CHECKSUM COMES FROM. The model recovered from the hermes distro's
# .vhdx hashes to exactly the upstream Hugging Face LFS oid, so the dead service
# ran the stock model and this container can rebuild it from upstream and prove
# it got the same bytes. A truncated download is what this catches; a corrupt
# model is otherwise reported only as garbage transcripts.
ENV MODEL_DIR=/models \
    MODEL_NAME=ggml-base.en.bin \
    WHISPER_HOST=0.0.0.0 \
    WHISPER_PORT=8090
VOLUME ["/models"]
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
