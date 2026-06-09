"""D&D 5e reference data for character building.

Sources: Player's Handbook (PHB), Xanathar's Guide to Everything (XGtE),
Tasha's Cauldron of Everything (TCoE), Volo's Guide to Monsters,
Mordenkainen's Tome of Foes, Eberron: Rising from the Last War,
Monsters of the Multiverse (MotM).
"""

# ──────────────────────────────────────────────
# Alignments (9 standard + Unaligned)
# ──────────────────────────────────────────────
ALIGNMENTS: list[str] = [
    "Lawful Good",
    "Neutral Good",
    "Chaotic Good",
    "Lawful Neutral",
    "True Neutral",
    "Chaotic Neutral",
    "Lawful Evil",
    "Neutral Evil",
    "Chaotic Evil",
    "Unaligned",
]

# ──────────────────────────────────────────────
# Races — PHB + supplement sourcebooks
# Subraces listed as separate entries for clarity.
# ──────────────────────────────────────────────
RACES: list[str] = [
    # PHB
    "Dragonborn",
    "Hill Dwarf",
    "Mountain Dwarf",
    "Drow (Dark Elf)",
    "High Elf",
    "Wood Elf",
    "Forest Gnome",
    "Rock Gnome",
    "Half-Elf",
    "Half-Orc",
    "Lightfoot Halfling",
    "Stout Halfling",
    "Human",
    "Variant Human",
    "Tiefling",
    # Volo's Guide to Monsters
    "Aasimar",
    "Protector Aasimar",
    "Scourge Aasimar",
    "Fallen Aasimar",
    "Bugbear",
    "Firbolg",
    "Goblin",
    "Goliath",
    "Hobgoblin",
    "Kenku",
    "Kobold",
    "Lizardfolk",
    "Orc",
    "Tabaxi",
    "Triton",
    "Yuan-Ti Pureblood",
    # Mordenkainen's Tome of Foes
    "Eladrin",
    "Sea Elf",
    "Shadar-Kai",
    "Deep Gnome (Svirfneblin)",
    "Duergar",
    "Githyanki",
    "Githzerai",
    # Eberron / Tasha's
    "Changeling",
    "Kalashtar",
    "Shifter",
    "Warforged",
    "Custom Lineage",
    # Monsters of the Multiverse / Other supplements
    "Aarakocra",
    "Air Genasi",
    "Earth Genasi",
    "Fire Genasi",
    "Water Genasi",
    "Tortle",
    "Harengon",
    "Owlin",
    "Fairy",
    "Satyr",
    "Centaur",
    "Minotaur",
    "Loxodon",
    "Simic Hybrid",
    "Vedalken",
    "Leonin",
    "Grung",
    "Verdan",
]

# ──────────────────────────────────────────────
# Classes (12 PHB + Artificer)
# ──────────────────────────────────────────────
CLASSES: list[str] = [
    "Artificer",
    "Barbarian",
    "Bard",
    "Cleric",
    "Druid",
    "Fighter",
    "Monk",
    "Paladin",
    "Ranger",
    "Rogue",
    "Sorcerer",
    "Warlock",
    "Wizard",
]

# ──────────────────────────────────────────────
# Subclasses per class
# Sources: PHB, XGtE, TCoE, Eberron (Artificer)
# ──────────────────────────────────────────────
SUBCLASSES: dict[str, list[str]] = {
    "Artificer": [
        "Alchemist",
        "Armorer",
        "Artillerist",
        "Battle Smith",
    ],
    "Barbarian": [
        "Path of the Berserker",
        "Path of the Totem Warrior",
        "Path of the Ancestral Guardian",
        "Path of the Storm Herald",
        "Path of the Zealot",
        "Path of the Beast",
        "Path of Wild Magic",
    ],
    "Bard": [
        "College of Lore",
        "College of Valor",
        "College of Glamour",
        "College of Swords",
        "College of Whispers",
        "College of Creation",
        "College of Eloquence",
    ],
    "Cleric": [
        "Knowledge Domain",
        "Life Domain",
        "Light Domain",
        "Nature Domain",
        "Tempest Domain",
        "Trickery Domain",
        "War Domain",
        "Forge Domain",
        "Grave Domain",
        "Order Domain",
        "Peace Domain",
        "Twilight Domain",
    ],
    "Druid": [
        "Circle of the Land",
        "Circle of the Moon",
        "Circle of Dreams",
        "Circle of the Shepherd",
        "Circle of Spores",
        "Circle of Stars",
        "Circle of Wildfire",
    ],
    "Fighter": [
        "Battle Master",
        "Champion",
        "Eldritch Knight",
        "Arcane Archer",
        "Cavalier",
        "Samurai",
        "Echo Knight",
        "Psi Warrior",
        "Rune Knight",
    ],
    "Monk": [
        "Way of the Open Hand",
        "Way of Shadow",
        "Way of the Four Elements",
        "Way of the Drunken Master",
        "Way of the Kensei",
        "Way of the Sun Soul",
        "Way of the Astral Self",
        "Way of Mercy",
    ],
    "Paladin": [
        "Oath of Devotion",
        "Oath of the Ancients",
        "Oath of Vengeance",
        "Oath of Conquest",
        "Oath of Redemption",
        "Oath of Glory",
        "Oath of the Watchers",
    ],
    "Ranger": [
        "Beast Master",
        "Hunter",
        "Gloom Stalker",
        "Horizon Walker",
        "Monster Slayer",
        "Fey Wanderer",
        "Swarmkeeper",
    ],
    "Rogue": [
        "Arcane Trickster",
        "Assassin",
        "Thief",
        "Inquisitive",
        "Mastermind",
        "Scout",
        "Phantom",
        "Soulknife",
    ],
    "Sorcerer": [
        "Draconic Bloodline",
        "Wild Magic",
        "Divine Soul",
        "Shadow Magic",
        "Storm Sorcery",
        "Aberrant Mind",
        "Clockwork Soul",
    ],
    "Warlock": [
        "The Archfey",
        "The Fiend",
        "The Great Old One",
        "The Celestial",
        "The Hexblade",
        "The Fathomless",
        "The Genie",
    ],
    "Wizard": [
        "School of Abjuration",
        "School of Conjuration",
        "School of Divination",
        "School of Enchantment",
        "School of Evocation",
        "School of Illusion",
        "School of Necromancy",
        "School of Transmutation",
        "War Magic",
        "Bladesinging",
        "Order of Scribes",
    ],
}

# ──────────────────────────────────────────────
# Backgrounds — PHB + expansion sourcebooks
# ──────────────────────────────────────────────
BACKGROUNDS: list[str] = [
    # PHB
    "Acolyte",
    "Charlatan",
    "Criminal",
    "Entertainer",
    "Folk Hero",
    "Gladiator",
    "Guild Artisan",
    "Guild Merchant",
    "Hermit",
    "Knight",
    "Noble",
    "Outlander",
    "Pirate",
    "Sage",
    "Sailor",
    "Soldier",
    "Spy",
    "Urchin",
    # Sword Coast Adventurer's Guide
    "City Watch",
    "Clan Crafter",
    "Cloistered Scholar",
    "Courtier",
    "Faction Agent",
    "Far Traveler",
    "Inheritor",
    "Knight of the Order",
    "Mercenary Veteran",
    "Urban Bounty Hunter",
    "Uthgardt Tribe Member",
    "Waterdhavian Noble",
    # Curse of Strahd / Gothic
    "Haunted One",
    # Ghosts of Saltmarsh
    "Fisher",
    "Marine",
    "Shipwright",
    "Smuggler",
    # Tomb of Annihilation / Other
    "Anthropologist",
    "Archaeologist",
    # Investigator variant
    "Investigator",
    # Wild Beyond the Witchlight
    "Feylost",
    "Witchlight Hand",
]

# ──────────────────────────────────────────────
# Feats — PHB (alphabetical)
# ──────────────────────────────────────────────
FEATS: list[str] = [
    "Actor",
    "Alert",
    "Athlete",
    "Charger",
    "Crossbow Expert",
    "Defensive Duelist",
    "Dual Wielder",
    "Dungeon Delver",
    "Durable",
    "Elemental Adept",
    "Grappler",
    "Great Weapon Master",
    "Healer",
    "Heavily Armored",
    "Heavy Armor Master",
    "Inspiring Leader",
    "Keen Mind",
    "Lightly Armored",
    "Linguist",
    "Lucky",
    "Mage Slayer",
    "Magic Initiate",
    "Martial Adept",
    "Medium Armor Master",
    "Mobile",
    "Moderately Armored",
    "Mounted Combatant",
    "Observant",
    "Polearm Master",
    "Resilient",
    "Ritual Caster",
    "Savage Attacker",
    "Sentinel",
    "Sharpshooter",
    "Shield Master",
    "Skilled",
    "Skulker",
    "Spell Sniper",
    "Tavern Brawler",
    "Tough",
    "War Caster",
    "Weapon Master",
]

# Pre-populated passive bonuses for feats with mechanical stat effects.
# Feats without passive bonuses get empty dicts (still selectable in UI).
# Users can customize values after selection.
FEAT_DATA: dict[str, dict] = {
    "Actor": {
        "description": "+1 CHA, advantage on Deception/Performance checks when pretending.",
        "bonus_ability_scores": {"charisma": 1},
    },
    "Alert": {
        "description": "+5 initiative, can't be surprised while conscious.",
        "bonus_initiative": 5,
    },
    "Athlete": {
        "description": "+1 STR or DEX, climbing doesn't cost extra movement.",
        "bonus_ability_scores": {"strength": 1},
    },
    "Charger": {
        "description": "Bonus action attack/shove after Dash action.",
    },
    "Crossbow Expert": {
        "description": "Ignore loading, no disadvantage at close range, bonus action crossbow attack.",
    },
    "Defensive Duelist": {
        "description": "Reaction to add proficiency to AC when wielding finesse weapon.",
    },
    "Dual Wielder": {
        "description": "+1 AC when dual wielding, draw/stow two weapons.",
        "bonus_ac": 1,
    },
    "Dungeon Delver": {
        "description": "Advantage on Perception/Investigation for traps, resistance to trap damage.",
    },
    "Durable": {
        "description": "+1 CON, minimum on hit dice healing.",
        "bonus_ability_scores": {"constitution": 1},
    },
    "Elemental Adept": {
        "description": "Spells ignore resistance to chosen element, treat 1s as 2s.",
    },
    "Grappler": {
        "description": "Advantage on attacks vs grappled targets, can pin creatures.",
    },
    "Great Weapon Master": {
        "description": "Bonus action attack on crit/kill, -5 to hit for +10 damage.",
    },
    "Healer": {
        "description": "Stabilize with healer's kit restores 1 HP, use kit for healing.",
    },
    "Heavily Armored": {
        "description": "+1 STR, gain heavy armor proficiency.",
        "bonus_ability_scores": {"strength": 1},
    },
    "Heavy Armor Master": {
        "description": "+1 STR, reduce nonmagical bludgeoning/piercing/slashing by 3.",
        "bonus_ability_scores": {"strength": 1},
    },
    "Inspiring Leader": {
        "description": "Give temp HP to allies after a 10-minute speech.",
    },
    "Keen Mind": {
        "description": "+1 INT, always know north, track time, recall anything from past month.",
        "bonus_ability_scores": {"intelligence": 1},
    },
    "Lightly Armored": {
        "description": "+1 STR or DEX, gain light armor proficiency.",
        "bonus_ability_scores": {"dexterity": 1},
    },
    "Linguist": {
        "description": "+1 INT, learn 3 languages, create written ciphers.",
        "bonus_ability_scores": {"intelligence": 1},
    },
    "Lucky": {
        "description": "3 luck points per long rest to reroll d20s.",
    },
    "Mage Slayer": {
        "description": "Reaction attack on adjacent caster, advantage on saves vs adjacent spells.",
    },
    "Magic Initiate": {
        "description": "Learn 2 cantrips and 1 first-level spell from a class.",
    },
    "Martial Adept": {
        "description": "Learn 2 maneuvers, gain 1 superiority die (d6).",
    },
    "Medium Armor Master": {
        "description": "No stealth disadvantage in medium armor, max DEX bonus +3.",
    },
    "Mobile": {
        "description": "+10 speed, Dash through difficult terrain, no OA after melee.",
        "bonus_speed": 10,
    },
    "Moderately Armored": {
        "description": "+1 STR or DEX, gain medium armor and shield proficiency.",
        "bonus_ability_scores": {"dexterity": 1},
    },
    "Mounted Combatant": {
        "description": "Advantage vs smaller unmounted, redirect attacks to mount.",
    },
    "Observant": {
        "description": "+1 INT or WIS, +5 passive Perception and Investigation.",
        "bonus_ability_scores": {"wisdom": 1},
    },
    "Polearm Master": {
        "description": "Bonus action butt strike, OA when enemies enter reach.",
    },
    "Resilient": {
        "description": "+1 to chosen ability, gain saving throw proficiency in it.",
    },
    "Ritual Caster": {
        "description": "Learn ritual spells from a class list.",
    },
    "Savage Attacker": {
        "description": "Reroll melee damage once per turn, use higher result.",
    },
    "Sentinel": {
        "description": "OA on Disengage, reduce speed to 0 on OA hit.",
    },
    "Sharpshooter": {
        "description": "No disadvantage at long range, ignore cover, -5/+10 option.",
    },
    "Shield Master": {
        "description": "Bonus action shove after Attack, add shield AC to DEX saves.",
    },
    "Skilled": {
        "description": "Gain proficiency in 3 skills or tools.",
    },
    "Skulker": {
        "description": "Hide when lightly obscured, missing ranged doesn't reveal position.",
    },
    "Spell Sniper": {
        "description": "Double spell range, ignore half/three-quarters cover, learn a cantrip.",
    },
    "Tavern Brawler": {
        "description": "+1 STR or CON, proficient with improvised weapons, grapple as bonus.",
        "bonus_ability_scores": {"strength": 1},
    },
    "Tough": {
        "description": "HP max increases by 2 per level.",
    },
    "War Caster": {
        "description": "Advantage on concentration saves, somatic with hands full, spell as OA.",
    },
    "Weapon Master": {
        "description": "+1 STR or DEX, proficiency with 4 weapons.",
        "bonus_ability_scores": {"strength": 1},
    },
}
