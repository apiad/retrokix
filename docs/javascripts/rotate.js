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

  /** Console label shown on the bezel — short enough to fit at 7px. */
  const LABEL_GBA  = "GAME BOY ADVANCE";
  const LABEL_NES  = "NINTENDO ENT. SYSTEM";
  const LABEL_SNES = "SUPER NINTENDO";

  /** @type {Game[]}
   * Top picks per console: 4 GBA + 3 NES + 3 SNES, interleaved so the
   * marquee cycles through every console in every pass. */
  const GAMES = [
    {
      slug: "pokemon-emerald",
      title: "Pokémon Emerald",
      label: LABEL_GBA,
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
      slug: "super-mario-world",
      title: "Super Mario World",
      label: LABEL_SNES,
      download: "super mario world",
      rom: "mario world",
      plugin: "retrokix.plugins.smw_progress",
      route: "/plugins/smw_progress/state",
      json: `{
  "world": "donut_plains",
  "level": "secret_1",
  "lives": 7, "coins": 42,
  "yoshi": "green",
  "powerup": "cape",
  "exits_unlocked": 26
}`,
    },
    {
      slug: "super-mario-bros",
      title: "Super Mario Bros.",
      label: LABEL_NES,
      download: "super mario bros",
      rom: "smb",
      plugin: "retrokix.plugins.smb_state",
      route: "/plugins/smb_state/state",
      json: `{
  "world": "1-1",
  "score": 12500,
  "lives": 3,
  "coins": 8,
  "powerup": "fire",
  "time_remaining": 287
}`,
    },
    {
      slug: "zelda-minish-cap",
      title: "Zelda: The Minish Cap",
      label: LABEL_GBA,
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
      slug: "zelda-link-to-the-past",
      title: "Zelda: A Link to the Past",
      label: LABEL_SNES,
      download: "zelda link to the past",
      rom: "link to the past",
      plugin: "retrokix.plugins.lttp_inventory",
      route: "/plugins/lttp_inventory/inventory",
      json: `{
  "hearts": 7.5, "max_hearts": 10,
  "rupees": 218,
  "sword": "master",
  "shield": "fire",
  "pendants": ["courage", "power"],
  "dungeon": "tower_of_hera"
}`,
    },
    {
      slug: "legend-of-zelda-nes",
      title: "The Legend of Zelda",
      label: LABEL_NES,
      download: "legend of zelda",
      rom: "zelda",
      plugin: "retrokix.plugins.zelda1_inventory",
      route: "/plugins/zelda1_inventory/inventory",
      json: `{
  "hearts": 4, "max_hearts": 6,
  "rupees": 73,
  "sword": "white",
  "bombs": 8, "max_bombs": 12,
  "triforce_pieces": 2,
  "overworld": "lake_hylia"
}`,
    },
    {
      slug: "metroid-fusion",
      title: "Metroid Fusion",
      label: LABEL_GBA,
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
      slug: "chrono-trigger",
      title: "Chrono Trigger",
      label: LABEL_SNES,
      download: "chrono trigger",
      rom: "chrono",
      plugin: "retrokix.plugins.chrono_party",
      route: "/plugins/chrono_party/party",
      json: `{
  "era": "600_AD",
  "active": ["Crono", "Marle", "Frog"],
  "gold": 4720,
  "crono": { "lv": 22, "hp": 374, "mp": 41 },
  "next_event": "magus_lair"
}`,
    },
    {
      slug: "castlevania-aria-of-sorrow",
      title: "Castlevania: Aria of Sorrow",
      label: LABEL_GBA,
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
      slug: "mega-man-2",
      title: "Mega Man 2",
      label: LABEL_NES,
      download: "mega man 2",
      rom: "mega man 2",
      plugin: "retrokix.plugins.mm2_loadout",
      route: "/plugins/mm2_loadout/loadout",
      json: `{
  "stage": "wood_man",
  "lives": 5,
  "health": 24,
  "weapons": ["mega_buster", "metal_blade", "air_shooter"],
  "etanks": 2,
  "robot_masters_defeated": 5
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
      } else if (key === "label") {
        next = game.label;
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


