/*
 * retrokix landing — rotating game showcase.
 *
 * Cross-fades title / image / curl JSON / install commands / plugin slug
 * across ~10 well-known GBA games on a fixed tick. Pauses on hover
 * over the hero or the install code so the visitor can actually read
 * what's frozen. Respects prefers-reduced-motion.
 *
 * Each [data-gx-rot="<key>"] element gets swapped in lockstep. The
 * image swap uses two stacked <img> tags (current + next) and toggles
 * opacity so the transition stays smooth even on first paint after a
 * cache miss.
 */

(() => {
  const TICK_MS = 4500;
  const FADE_MS = 320;

  /** @typedef {{ slug: string, title: string, download: string, rom: string,
   *             plugin: string, route: string, json: string }} Game */

  /** @type {Game[]} */
  const GAMES = [
    {
      slug: "pokemon-emerald",
      title: "Pokémon Emerald",
      download: "pokemon emerald",
      rom: "emerald",
      plugin: "retrokix.plugins.emerald_party",
      route: "/plugins/emerald_party/party",
      json: `{
  "slots": [
    { "species": 281,
      "nickname": "COMBUSKEN",
      "level": 16,
      "hp": 50, "max_hp": 50,
      "friendship": 73 }
  ]
}`,
    },
    {
      slug: "zelda-minish-cap",
      title: "Zelda: The Minish Cap",
      download: "zelda minish cap",
      rom: "minish-cap",
      plugin: "retrokix.plugins.zelda_inventory",
      route: "/plugins/zelda_inventory/inventory",
      json: `{
  "hearts": 9,
  "max_hearts": 12,
  "rupees": 142,
  "kinstones": 7,
  "current_item": "boomerang",
  "dungeon": "deepwood_shrine"
}`,
    },
    {
      slug: "metroid-fusion",
      title: "Metroid Fusion",
      download: "metroid fusion",
      rom: "metroid-fusion",
      plugin: "retrokix.plugins.samus_status",
      route: "/plugins/samus_status/status",
      json: `{
  "energy": 199, "max_energy": 299,
  "missiles": 12, "max_missiles": 30,
  "suit": "varia",
  "area": "sector_2_trauma_ward",
  "items": ["morph_ball", "bombs", "charge_beam"]
}`,
    },
    {
      slug: "castlevania-aria-of-sorrow",
      title: "Castlevania: Aria of Sorrow",
      download: "castlevania aria of sorrow",
      rom: "aria-of-sorrow",
      plugin: "retrokix.plugins.aria_souls",
      route: "/plugins/aria_souls/souls",
      json: `{
  "level": 14,
  "hp": 145, "mp": 38,
  "hearts": 22,
  "equipped_soul": "skeleton_blaze",
  "souls_collected": 47,
  "area": "study"
}`,
    },
    {
      slug: "advance-wars",
      title: "Advance Wars",
      download: "advance wars",
      rom: "advance-wars",
      plugin: "retrokix.plugins.aw_battlefield",
      route: "/plugins/aw_battlefield/state",
      json: `{
  "day": 7,
  "current_co": "andy",
  "funds": 4200,
  "units": 9, "enemy_units": 11,
  "captured_props": 6,
  "weather": "clear"
}`,
    },
    {
      slug: "final-fantasy-tactics-advance",
      title: "Final Fantasy Tactics Advance",
      download: "final fantasy tactics advance",
      rom: "ffta",
      plugin: "retrokix.plugins.ffta_clan",
      route: "/plugins/ffta_clan/roster",
      json: `{
  "clan": "Cygnus",
  "law": "no_fire",
  "missions_cleared": 23,
  "leader": { "name": "Marche",
              "job": "Hunter",
              "level": 18,
              "race": "human" }
}`,
    },
    {
      slug: "mario-luigi-superstar-saga",
      title: "Mario & Luigi: Superstar Saga",
      download: "mario luigi superstar saga",
      rom: "mlss",
      plugin: "retrokix.plugins.mlss_bros",
      route: "/plugins/mlss_bros/status",
      json: `{
  "mario": { "hp": 84, "bp": 24, "level": 12 },
  "luigi": { "hp": 78, "bp": 28, "level": 12 },
  "coins": 312,
  "bros_attack": "splash_bros"
}`,
    },
    {
      slug: "golden-sun",
      title: "Golden Sun",
      download: "golden sun",
      rom: "golden-sun",
      plugin: "retrokix.plugins.golden_sun_djinn",
      route: "/plugins/golden_sun_djinn/party",
      json: `{
  "leader": "Isaac",
  "level": 16,
  "hp": 178, "pp": 47,
  "djinn": { "venus": 5, "mars": 3 },
  "psynergy": ["move", "growth", "ragnarok"]
}`,
    },
    {
      slug: "wario-land-4",
      title: "Wario Land 4",
      download: "wario land 4",
      rom: "wario-land-4",
      plugin: "retrokix.plugins.wario_run",
      route: "/plugins/wario_run/state",
      json: `{
  "level": "the_curious_factory",
  "coins": 87,
  "treasures": 3, "max_treasures": 4,
  "time_remaining_s": 142,
  "form": "puffy"
}`,
    },
    {
      slug: "doom",
      title: "Doom",
      download: "doom",
      rom: "doom",
      plugin: "retrokix.plugins.doom_hud",
      route: "/plugins/doom_hud/state",
      json: `{
  "map": "E1M2",
  "health": 67, "armor": 50,
  "weapon": "shotgun",
  "ammo": { "shells": 18, "bullets": 100 },
  "kills": 12, "secrets": 1
}`,
    },
  ];

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  /** Color a JSON literal with the same .t-k/.t-s/.t-n/.t-p tokens
   *  the static HTML uses. */
  function highlightJson(json) {
    const escaped = escapeHtml(json);
    return escaped
      .replace(
        /("(?:\\.|[^"\\])*")(\s*:)?/g,
        (_match, str, colon) =>
          colon
            ? `<span class="t-k">${str}</span>${colon}`
            : `<span class="t-s">${str}</span>`,
      )
      .replace(
        /(?<![\w"])(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?![\w"])/g,
        '<span class="t-n">$1</span>',
      )
      .replace(/([{}\[\]])/g, '<span class="t-p">$1</span>');
  }

  function applyGame(game, immediate) {
    // text rotators
    document.querySelectorAll("[data-gx-rot]").forEach((el) => {
      const key = el.dataset.gxRot;
      let next;
      if (key === "json") {
        next = highlightJson(game.json);
      } else if (key === "title") {
        next = game.title;
      } else if (key === "download") {
        next = game.download;
      } else if (key === "rom") {
        next = game.rom;
      } else if (key === "plugin") {
        next = game.plugin;
      } else if (key === "route") {
        next = game.route;
      } else {
        return;
      }

      const set = () => {
        if (key === "json") {
          el.innerHTML = next;
        } else {
          el.textContent = next;
        }
      };

      if (immediate) {
        set();
      } else {
        el.classList.add("gx-rot-fade-out");
        setTimeout(() => {
          set();
          el.classList.remove("gx-rot-fade-out");
        }, FADE_MS);
      }
    });

    // image rotator — use two stacked <img>s and toggle visible one.
    // Sprites were preloaded at init, so the swap is synchronous and
    // stays in lockstep with the text fade.
    const stack = document.querySelector(".gx-screen__img-stack");
    if (stack) {
      const layers = stack.querySelectorAll(".gx-screen__img");
      if (layers.length >= 2) {
        const visible = stack.querySelector(".gx-screen__img.is-visible");
        const hidden = visible === layers[0] ? layers[1] : layers[0];
        const src = `${stack.dataset.base}${game.slug}.png`;
        hidden.alt = `retrokix running ${game.title}`;
        if (hidden.getAttribute("src") !== src) {
          hidden.src = src;
        }
        const apply = () => {
          hidden.classList.add("is-visible");
          if (visible && visible !== hidden) {
            visible.classList.remove("is-visible");
          }
        };
        if (immediate) {
          apply();
        } else {
          setTimeout(apply, FADE_MS);
        }
      }
    }
  }

  function preloadSprites(base) {
    GAMES.forEach((g) => {
      const img = new Image();
      img.src = `${base}${g.slug}.png`;
    });
  }

  function init() {
    // Guard against double-init under Material's navigation.instant
    // / livereload, which would otherwise stack timer chains and
    // appear to "tick faster" with every reload.
    if (window.__gxRotInited) return;
    window.__gxRotInited = true;

    const stack = document.querySelector(".gx-screen__img-stack");
    if (!stack) return; // not on the landing page

    preloadSprites(stack.dataset.base);

    let idx = 0;
    applyGame(GAMES[idx], /* immediate */ true);

    if (prefersReducedMotion || GAMES.length < 2) return;

    let paused = false;
    let timer = null;

    function schedule() {
      timer = setTimeout(step, TICK_MS);
    }
    function step() {
      if (paused) {
        schedule();
        return;
      }
      idx = (idx + 1) % GAMES.length;
      applyGame(GAMES[idx], false);
      schedule();
    }

    // Pause when the user is hovering anything we're animating —
    // they probably want to read the frozen state.
    const pauseTargets = [
      document.querySelector(".gx-hero__visual"),
      document.querySelector(".gx-section--start"),
      document.querySelector(".gx-section--cta"),
    ].filter(Boolean);

    pauseTargets.forEach((el) => {
      el.addEventListener("mouseenter", () => {
        paused = true;
      });
      el.addEventListener("mouseleave", () => {
        paused = false;
      });
    });

    // Visibility — don't rotate on a backgrounded tab.
    document.addEventListener("visibilitychange", () => {
      paused = document.hidden;
    });

    schedule();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();


