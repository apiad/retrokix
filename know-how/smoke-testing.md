# Smoke-testing gbax

Quick end-to-end verification after any non-trivial runtime or API change.
Assumes `tests/fixtures/test.gba` and `tests/cores/mgba_libretro.so` are
present.

## `gbax serve` curl walk-through

```bash
source .venv/bin/activate
gbax serve tests/fixtures/test.gba --port 18420 &
SERVE_PID=$!
sleep 1

# Mode
curl -s http://127.0.0.1:18420/mode
# {"mode": "step"}

# Step 10 frames
curl -s -X POST 'http://127.0.0.1:18420/step?frames=10'
# {"frame_count": 10}

# Get frame as PNG
curl -s http://127.0.0.1:18420/frame -o /tmp/gbax-frame.png
file /tmp/gbax-frame.png
# PNG image data, 240 x 160, 8-bit/color RGB, non-interlaced

# Press buttons
curl -s -X POST http://127.0.0.1:18420/buttons \
    -H 'content-type: application/json' \
    -d '{"buttons": ["a","right"]}'

# Read EWRAM (0x02000000 = 33554432)
curl -s 'http://127.0.0.1:18420/memory?addr=33554432&len=16'

# Write then read back
curl -s -X POST http://127.0.0.1:18420/memory \
    -H 'content-type: application/json' \
    -d '{"addr": 33554432, "data": "deadbeef", "width": 4}'
curl -s 'http://127.0.0.1:18420/memory?addr=33554432&len=4'
# {"addr": 33554432, "len": 4, "data": "deadbeef"}

# Switch to free, watch frame count climb
curl -s -X POST http://127.0.0.1:18420/mode \
    -H 'content-type: application/json' \
    -d '{"mode":"free"}'
sleep 1
curl -s http://127.0.0.1:18420/frame_count
# frame_count > 60

kill $SERVE_PID
```

## `gbax play` (manual)

```bash
gbax play tests/fixtures/test.gba
```

- Window opens at 720×480 (240×160 × 3).
- Arrow keys / X (A button) / Z (B button) / Enter (Start) / RShift (Select) work.
- `1`-`9` save slot, `Shift+1`-`9` load slot, `Ctrl+S` persist slot,
  `F12` screenshot, `Tab` fast-forward (hold).
- Close window to exit.

Investigate before merging if any of the above doesn't behave as
documented.
