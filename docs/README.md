# gbax documentation

## The story

- [**concepts.md**](concepts.md) — the cooperative loop, the discovery
  toolkit, the two audiences (speedrun + neurosymbolic research),
  what this is *for*

## Discovery surfaces

- [**plugins.md**](plugins.md) — write Python that hooks the play
  loop, expose your own HTTP routes
- [**state-tracker.md**](state-tracker.md) — supervised memory
  inference: capture → compile → refine
- [**cookbook/emerald_party.md**](cookbook/emerald_party.md) —
  walk-through of the bundled Pokémon Emerald party plugin

## Reference

- [**cli.md**](cli.md) — every command and flag
- [**api.md**](api.md) — every HTTP endpoint
- [**installing.md**](installing.md) — install paths, bundled core,
  lookup order, supported platforms
- [**shaders.md**](shaders.md) — wgpu renderer, bundled CRT-Lottes,
  custom WGSL
- [**automation.md**](automation.md) — `gbax.Controller`, scenarios,
  tournaments (the offline counterpart to plugins)

## See also

- [Project README](../README.md) — pitch, three-command hero, roadmap
- [`know-how/building-libretro-core.md`](../know-how/building-libretro-core.md) —
  building `mgba_libretro.so` from source
- [`know-how/smoke-testing.md`](../know-how/smoke-testing.md) —
  end-to-end smoke recipe
