# Automation: Controller, Scenarios, Players

User-facing companion to the design spec
(`vault/Atlas/Architecture/2026-06-09-gbax-player-tournament-design.md`).

## Controller — pythonic gbax

`gbax.Controller` is the headless Python API. It wraps `EmulatorRuntime`
with blocking primitives, so scripts look like a person typing buttons.

```python
import gbax
with gbax.Controller("metroid fusion") as g:
    g.press(["start"], frames=2)
    g.wait(180)
    while g.read_u8(0x02000000) == 0:
        g.press(["a"], frames=1)
    g.screenshot("/tmp/now.png")
```

See `gbax.controller.Controller` for the full method list. Roughly:

- Driving: `press(buttons, frames)`, `hold(buttons)`, `release()`, `wait(frames)`
- Memory: `read_u8/u16/u32`, `read_bytes`, `write_*`
- Visual: `framebuffer`, `screenshot(path)`
- Saves: `save_state()`, `load_state(blob)`, `save_slot(N)`, `load_slot(N)`
- Cheats: `enable_cheat`, `disable_cheat`, `add_custom_cheat`

## Scenarios — turn a ROM into a runnable task

A scenario is a Python class with four required methods plus optional
teardown:

```python
class MyScenario(Scenario):
    name = "my-scenario"
    rom_sha1 = "<40 hex>"
    decision_period = 1                   # ask the player every frame
    max_frames = 18000                    # hard cap

    def setup(self, ctl): ...             # drive to start-of-match
    def observe(self, ctl, frame): ...    # JSON dict sent to the player
    def score(self, ctl, frame): ...      # dict with mandatory "score": float
    def done(self, ctl, frame): ...       # truthy → end match
    def teardown(self, ctl): ...          # optional
```

Scaffold one:

```
$ gbax scenario create "metroid fusion" --name escape
wrote /home/<you>/.gbax/scenarios/metroid-fusion__escape.py
```

List installed:

```
$ gbax scenario list
  mk-arcade-easy      MKArcadeEasy    src/gbax/data/scenarios/mk_arcade_easy.py
  smb3-world-1-1      SMB3World1_1    src/gbax/data/scenarios/smb3_world_1_1.py
  escape              Escape          ~/.gbax/scenarios/metroid-fusion__escape.py
```

Validate:

```
$ gbax scenario validate ~/.gbax/scenarios/metroid-fusion__escape.py
  OK    Escape  (name=escape)
```

## Players — subprocess stdio

Players are separate processes communicating with gbax over JSON
newline-delimited messages on stdin/stdout. The Python helper makes this
trivial:

```python
from gbax.player import run

def act(obs):
    if obs.get("level_clear"):
        return []
    return ["right", "b"]   # run right with B held

run(act, name="speedrun-bot")
```

Run it:

```
$ gbax train --rom "mario advance 4" \
    --scenario smb3-world-1-1 \
    --player ./speedrun_bot.py
```

The protocol is documented in
`vault/Atlas/Architecture/2026-06-09-gbax-player-tournament-design.md` —
any language that can read/write JSON on stdio works.

## Training (untimed) vs Tournament (60 fps wall clock)

- `gbax train` runs in step mode. The emulator advances only when the
  driver steps it. The player can take as long as it wants per
  observation. Used for RL training, evaluation, scenario debugging.
- `gbax tournament` runs in real time at 60 fps. The game keeps advancing
  whether or not the player has responded. The player has `decision_period
  × 16.67 ms` to think between observations; late responses still apply
  but count as a lag tick. After `--lag-forfeit` (default 60) cumulative
  misses → forfeit.

```
$ gbax tournament --rom "mortal kombat" \
    --scenario mk-arcade-easy \
    --player "python -m gbax.data.bots.press_a" \
    --player "python -m gbax.data.bots.random" \
    --player "./my_handcrafted_bot" \
    --output /tmp/mk-tourney
```

Output: terminal leaderboard + `/tmp/mk-tourney/results.json`.

## Bundled examples

- Scenarios: `gbax/data/scenarios/{mk_arcade_easy,smb3_world_1_1}.py`
- Players:   `gbax/data/bots/{press_a,random}.py`
