#!/bin/bash
# Deploys ~/.asoundrc on potato to fix the play-while-capture contention
# found live 2026-07-23 (bin/crt-earcon-loopback-test.py measured near-zero
# signal on the handset earcon path while capture was active -- card 1,
# "KT USB Audio", is used for both, and plain hw:/plughw: devices are
#   [rest: vault:crt/header-archaeology-20260817.md]
set -euo pipefail

cat > ~/.asoundrc <<'EOF'
pcm.crtmic_dsnoop {
    type dsnoop
    ipc_key 4141594
    slave {
        pcm "hw:CARD=Audio,DEV=0"
        channels 1
        rate 16000
        format S16_LE
        period_size 1024
        buffer_size 8192
    }
}
pcm.crtmic {
    type plug
    slave.pcm "crtmic_dsnoop"
}

pcm.crthandset_dmix {
    type dmix
    ipc_key 4141593
    slave {
        pcm "hw:CARD=Audio,DEV=0"
        channels 1
        rate 16000
        format S16_LE
        period_size 1024
        buffer_size 8192
    }
}
pcm.crthandset {
    type plug
    slave.pcm "crthandset_dmix"
}
EOF

echo "Deployed ~/.asoundrc. Next steps:"
echo "  1. Restart potato's stt tmux window with CRT_AUDIO_DEV=crtmic"
echo "  2. Update crt-earcon.sh's HANDSET_DEVICE default to 'crthandset' (or pass --device via CRT_EARCON_HANDSET_DEVICE=crthandset)"
echo "  3. Re-run: python3 bin/crt-earcon-loopback-test.py handset"
echo "     and confirm the detection ratio improves over the earlier 0.1x."
