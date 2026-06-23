"""Pokémon Emerald US v1.0 — EWRAM / IWRAM address constants.

ROM SHA1: f3ae088181bf583e55daf962a92bb46f4f1d07b7
All addresses verified empirically on this build. Source attribution
for each block lives in the comment above it (pokeemerald path).
"""
from __future__ import annotations

EMERALD_US_V10_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"

# --- Party slots ---
# Source: src/pokemon.c / include/pokemon.h struct Pokemon
PARTY_BASE = 0x020244EC     # gPlayerParty[0]
SLOT_SIZE = 100             # bytes per party slot
SLOT_COUNT = 6

# Offsets WITHIN a 100-byte party slot.
OFF_PERSONALITY = 0x00
OFF_OTID = 0x04
OFF_NICKNAME = 0x08
OFF_LANGUAGE = 0x12
OFF_CHECKSUM = 0x1C
OFF_ENC_BLOCK = 0x20        # 48 encrypted bytes (4 × 12-byte substructures)
OFF_STATUS = 0x50           # u32
OFF_LEVEL = 0x54            # u8
OFF_CURRENT_HP = 0x56       # u16_le
OFF_MAX_HP = 0x58           # u16_le
OFF_STAT_ATK = 0x5A
OFF_STAT_DEF = 0x5C
OFF_STAT_SPE = 0x5E
OFF_STAT_SPA = 0x60
OFF_STAT_SPD = 0x62

# 24 permutations of (Growth, Attacks, EVs, Misc), indexed by personality % 24.
SUBSTRUCT_ORDERS = [
    "GAEM", "GAME", "GEAM", "GEMA", "GMAE", "GMEA",
    "AGEM", "AGME", "AEGM", "AEMG", "AMGE", "AMEG",
    "EGAM", "EGMA", "EAGM", "EAMG", "EMGA", "EMAG",
    "MGAE", "MGEA", "MAGE", "MAEG", "MEGA", "MEAG",
]

# --- Battle state ---
# Source: src/battle_main.c, include/pokemon.h::BattlePokemon
GBATTLE_MONS_BASE = 0x02024084
GBATTLE_TYPE_FLAGS = 0x02022FEC
BATTLE_MON_SIZE = 88
OPP_SINGLES_SLOT = 1
BMON_PLAYER_SLOT = 0

# Offsets within a BattlePokemon.
BMON_OFF_SPECIES = 0x00
BMON_OFF_MOVES = 0x0C    # u16 × 4
BMON_OFF_TYPES = 0x21    # u8 × 2
BMON_OFF_PP = 0x24       # u8 × 4
BMON_OFF_HP = 0x28
BMON_OFF_LEVEL = 0x2A
BMON_OFF_MAX_HP = 0x2C

# --- Battle phase byte (interim; replaced by gMain.callback2 in slice 2) ---
# Empirically discovered. gBattleCommunication[MULTIUSE_STATE] — a generic
# loop counter reused by every sub-callback. Discriminator only across the
# specific snapshots we labeled. Phase 1 is ambiguous (text vs SHIFT submenu);
# slice 2 replaces this with gMain.callback2 for unambiguous screen identity.
BATTLE_PHASE_ADDR = 0x02024332

# --- Pokédex (SaveBlock2) ---
# gSaveBlock2Ptr (Emerald US v1.0) → SaveBlock2 in EWRAM. The Pokédex struct's
# owned/seen bitfields sit at the offsets below; bit index = national dex no - 1,
# 52 bytes each. Empirically validated against the bundled ROM + savestates
# (party species' national bits ⊆ owned ⊆ seen). See pokedex-caught-overlay design.
GSAVEBLOCK2_PTR = 0x03005D90
DEX_OWNED_OFF = 0x28
DEX_SEEN_OFF = 0x5C
DEX_FLAGS_BYTES = 52

# --- Trainer / SaveBlock1 (money, badges, play time, bag) ---
# Empirically validated against the bundled ROM + slot-1 save (ALEX, ID 31742,
# ₽8920, 1/8 badges, 16h40m, Poké-Ball ×3). See emerald-trainer-panel design.
GSAVEBLOCK1_PTR = 0x03005D8C
ENCRYPTION_KEY_OFF = 0x01F4  # in SaveBlock2; XORs money + bag quantities
MONEY_OFF = 0x0490  # in SaveBlock1; u32 ^ key
FLAGS_OFF = 0x1270  # in SaveBlock1; flag bitfield base
FLAG_BADGE01 = 0x867  # FLAG_BADGE01_GET .. +7 = the eight gym badges
PLAYTIME_HOURS_OFF = 0x0E  # in SaveBlock2 (u16); +0x10 minutes (u8), +0x11 seconds (u8)
TRAINER_NAME_OFF = 0x00  # in SaveBlock2 (8 bytes, gen-3 charmap)
TRAINER_GENDER_OFF = 0x08  # in SaveBlock2 (u8; 0 male, 1 female)
TRAINER_ID_OFF = 0x0A  # in SaveBlock2 (u16 public id)
# Bag pockets in SaveBlock1: (offset, slot_count). Slot = {u16 id, u16 qty^key16}.
BAG_POCKETS = {
    "Items": (0x0560, 30),
    "Key": (0x05D8, 30),
    "Balls": (0x0650, 16),
    "TMs": (0x0690, 64),
    "Berries": (0x0790, 46),
}

# --- Driver timing constants ---
SETTLE_FRAMES = 150
NAV_GAP_FRAMES = 8
PRESS_FRAMES = 3
MENU_TRANSITION_FRAMES = 30
PARTY_MENU_SETTLE_FRAMES = 90
