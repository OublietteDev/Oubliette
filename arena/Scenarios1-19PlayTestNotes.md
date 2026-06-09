#	Encounter	Grid	Party	Enemies	Primary Tests
1	Tavern Brawl	15×10	Thorin + Ser Marcus	4 Goblins	Basic melee, initiative, death saves
2	Ambush at the Bridge	20×12	Kael + Shade	3 Hobgoblins	Cover AC, water/difficult terrain, ranged combat
3	Wizard's Duel	15×15	Elara	1 Mage	Save effects, Hold Person paralysis, concentration, spell resources
4	Hold the Line	15×12	Thorin + Marcus + Aldric	4 Wolves	Opportunity attacks, Dodge/Disengage/Help, chokepoint
5	Dragon's Lair	25×20	Marcus + Elara + Aldric + Shade	Young Red Dragon	Large creature footprint, reach, breath weapon AoE
6	The Gauntlet	20×15	Valeria + Zara	3 Ogres	Equipment AC stacking, feat bonuses, ki/smite resource costs
7	Undead Siege	18×12	Aldric + Thorin	3 Skeletons + 3 Zombies	Bludgeoning vulnerability, poison immunity, condition immunity
8	Boss Rush	30×25	Marcus + Elara + Aldric + Shade	Kraken + 2 Sahuagin	Gargantuan 19-hex, water terrain, full stress test

User notes on encounter 1:
-Left clicking on a downed entity seems to cause a crash (Fixed)
-Death save system does not appear to even be implemented? (Fixed, just not super obvious yet)
-When there are too many scenarios in the "Load Encounter" screen, you cannot scroll (not related to encounter 1, but something I noticed) (Fixed).
-Melee appears to work as desired (attacks follow specific range, proc, has to overcome AC, etc.)
-Observed random crash when a goblin moved into zone of control of Thorin and Ser Marcus; unable to reproduce (Did not observe again)
-Able to both win and be defeated as expected
-Both Thorin and Ser Marcus seem to have Action Surge, but I didn't observe a way to utizlie this ability (Fixed)

User notes on encounter 2:
-It seems cover system works - need clarification on whether you have to be on the cover hex or just near adjacent to it. If just adjacent, it doesn't make sense (since you can be next to the cover but in full view of the enemy; why would the entity receive the buff?) (Clarification: Cover works by checking INTERVENING hexes between attacker and target -- you do NOT stand on the cover hex. A cover hex between the two combatants grants the AC bonus. This is correct per 5e rules: cover is an obstacle between you and the attacker. Adjacent combatants [distance 1] never get cover from terrain.)
-Need to add color coding for ranged attacks, similar to movement color coding so that players know the exact range of their weapons (Fixed -- warm orange overlay shows normal range, dimmer overlay shows long/disadvantage range during AWAITING_ACTION phase)
-Ranged combat works well
-Terrain system seems to work (difficult terrain costs double movement, cannot overcome wall). Water does not seem to cause additional movement penalties. (Clarification: Water DOES cost double movement [10 ft per hex, same as difficult terrain]. This is correct per 5e rules where water counts as difficult terrain. The visual feedback may not have been obvious -- both water and difficult terrain cost 10 ft vs the normal 5 ft per hex.)

User notes on encounter 3:
-Spell slots do not function as expected; you can make a class resource "Level 1 Spell Slots", but the spell slots in the features section do nothing (Fixed -- spell_slots now auto-sync into class_resources on character load. A model_validator on PlayerCharacter bridges spell_slots {1: 4, 2: 3, 3: 2} into class_resources {"spell_slot_1": 4, "spell_slot_2": 3, "spell_slot_3": 2}. All of Elara's spells now have working resource costs.)
-Elara Nightwhisper does not have the spells that we are trying to examine, meaning I cannot play test these unless Archmage Kessler uses them on the player (hold person, a spell with concentration, paralysis, etc.) (Fixed -- Added Hold Person to Elara's actions: WIS save DC 15, applies paralyzed on fail, requires concentration, costs a 2nd-level spell slot. Also added hold_person to her spells_prepared list.)
-Target does not roll repeat saving throw at end of turn when paralyzed by Hold Person; turn is 100% skipped (Fixed -- resolve_effect() now passes duration_type="end_of_turn", save_to_end, and save_dc to apply_condition(). The end-of-turn processing code already existed but was never receiving the save parameters.)
-No other entity to hit Elara to observe concentration CON save (Clarification: Concentration CON saves on damage are fully implemented and tested in code. To observe in this 1v1 scenario, the Mage must attack Elara while she concentrates. The Mage's AI should do this naturally.)
-Cannot drop concentration voluntarily as a player (Fixed -- Added "Drop Conc." button to radial menu. Appears only when concentrating, shows what spell is active, costs no action.)
-Elara has no second concentration spell to test casting-replaces-concentration (Fixed -- Added Web spell: DEX save DC 15, applies restrained on fail, requires concentration, costs 2nd-level slot. Casting Web while concentrating on Hold Person will auto-drop Hold Person first.)
-If target saves successfully against a concentration spell, caster still begins concentrating (Fixed -- resolve_effect() now tracks which conditions were actually applied. Concentration only starts if at least one condition landed on a target. If the target saves, no concentration begins.)
-Casting a new concentration spell (e.g. Web) while concentrating on Hold Person keeps both effects on the target instead of ending the first (Fixed -- Concentration system now uses linked target tracking. When concentration ends for any reason, all conditions tied to that spell are removed from their targets. The CONCENTRATING condition stores linked_targets in extra_data, mapping each target/condition pair back to the caster's spell.)
-Breaking concentration via failed CON save does not remove the spell's conditions from targets (Fixed -- Same linked target tracking system. end_concentration() reads linked_targets from the CONCENTRATING condition's extra_data and removes each linked condition from the corresponding target creature.)

User notes on encounter 4:
-All systems appear to work well; uncertain what is meant by testing "Help", however. Can confirm that disengage, opportunity attacks, and dodge all function well. (Clarification + Fix -- The Help action is a 5e standard action that gives an adjacent ally advantage on their next attack roll. It was fully implemented in the backend but was missing from the Tactics popup in the GUI. Now added: click Help in the Tactics menu, then click an adjacent ally to grant them advantage. Uses your action for the turn.)
-Small note on cramped space: dead bodies are not traversible. Therefore, if there is a chokepoint that gets clogged due to too many dead bodies, and the surviving entities on either team don't have ranged attacks, then the encounter cannot end. (Fixed -- Per 5e rules, a dead creature's space is now treated as difficult terrain [costs 10 ft to enter] rather than impassable. Living creatures can both move through and stop on dead creature hexes. This applies to player movement, AI movement, and AI pathfinding.)

User notes on encounter 5:
-The hitbox for the large creature is strange. When standing directly next it, I was unable to execute a melee attack; by relocating, I was able to execute the attack. Because it is comprised of 3 hexes rather than a singular hex, the tool might think only one of the hexes is capable of being attacked. (Fixed -- Root cause: resolve_attack() and resolve_effect() used grid.find_creature() to look up positions, which returns an arbitrary hex of a multi-hex creature rather than the canonical anchor. The footprint distance calculation then used this wrong hex as the anchor, generating incorrect footprint geometry and wrong distances. Fix: added optional attacker_pos/target_pos parameters to resolve_attack() and resolve_effect(), and all callers [manager, reactions, ready_action] now pass combatant.position [the true anchor] explicitly.)
-The young red dragon appears unwilling to use its breath attack, so I do not know if it works or not. (Fixed -- THREE issues found and resolved: [1] AI scoring: The scoring pipeline only evaluated attacks, heals, and standard actions. Added "effect" action category with score_effect_action() for save-based damage/condition actions. [2] AI resource conservation: should_use_limited_ability() was too aggressive about conserving single-use abilities early in battle. High-priority actions [ai_priority >= 8] now bypass the conservation penalty, so signature moves like breath weapons are used when tactically appropriate. [3] AoE single-target: execute_effect() only resolved against the one clicked/selected target. Now detects area target types [area_cone, area_sphere, etc.] and expands to ALL conscious creatures within area_size feet of the caster. Resource costs and use tracking only deducted once. Each affected creature makes its own saving throw independently.)
-Uncertain what "reach" is meant to test. (Clarification: "Reach" refers to the 5e weapon/creature property where some attacks have a reach greater than the standard 5 ft. A Young Red Dragon's bite has 10 ft reach and claws have 5 ft reach. The simulator already handles reach via the action.attack.reach field -- is_in_range() checks distance_feet <= action.attack.reach for melee attacks. The multi-hex footprint fix above also ensures reach calculations are accurate for Large+ creatures, since min_distance_between() now receives the correct anchor positions.)

User notes on encounter 6:
-Features don't seem to do anything; they are basically just descriptions, it seems. This is unhelpful for gameplay purposes. (Fixed x2)
-Feats (which seem to be distinct and come from a dropdown box in the Features sections in the character creator) also don't seem to do anything; there is no easy way to tell. We may want to add a tooltip when mousing over a character's stats in the combat UI that breaks down where the bonuses they receive are coming from (helps inform player + debugging) (Fixed, tooltips added; tooltips may need reworked in the future for ease of use/reading)
-Casting lay on hands appears to crash the game (Fixed)
-There appears to be no way to cast divine smite (perhaps a pop up that asks the player if they want to smite and at what level if a successful attack? Then damage is calculated?) (Fixed and implemented)
-Class resources (Ki for example) appear to be used appropriately when they don't break the game (like lay on hands above) (Fixed; class resources seemed to be decoupling the aforementioned skill from the action economy, making them infinitely usable until the class resource ran out)
-Adding a +2 AC ring of protection to Zara (added as gear, placed in Ring 1 slot) reduced that character's AC by 1 (from 17 to 16)? (Fixed)

User notes on encounter 7:
-Poison doesn't appear to apply (user gave Thorin a poison attack that adds the poisoned debuff and exhaustion and tested it on goblins in a different scenario; neither seemed to apply) (Fixed -- resolve_attack_damage() was missing condition application logic. When an attack action has conditions_applied set, these conditions were never applied to the target on a hit. The code path existed in resolve_effect() for non-attack actions but was absent from the attack pipeline. Added the missing loop after damage application in resolve_attack_damage().)
-Spirit guardians just doesn't seem to work at all; would also be nice if there was some indicator on the field that showed the range of spirit guardians; the spell in Brother Aldric's character sheet seems blank. Is this because when the character sheet was being created, there was no capability to do persistent, AoE spells? Might need added, good find. (Fixed -- Spirit Guardians was defined with target_type "self", no saving_throw, and no area_size, so it produced no mechanical effect. Updated brother_aldric.json with proper fields: target_type "area_sphere", area_size 15, saving_throw with WIS DC 15 for 3d8 radiant [half on success]. Currently functions as a one-time AoE burst when cast. True persistent per-turn zone damage [damage when enemies start turn in area or enter it] is not yet implemented -- this requires the AreaZone system from CombatEffectDesignDocument.md Section 7.9. Visual AoE indicator on the grid is also not yet implemented.)
-Vulnerabilities worked excellently
User notes after first round of fixes for encounter 7:
-Spirit guardians harms allies (I believe this is not the way it is intended to work?) (Fixed -- _resolve_effect_targets() in manager.py was hitting ALL creatures in the AoE regardless of faction. Added team-based filtering: harmful AoE effects [saving throw damage, conditions] now only target enemies, while beneficial AoE effects [healing] only target allies. Uses the caster's team field to determine friend vs foe.)
-Spirit guardians does not persist (this was noted above in the fix; reiterating here for additional visibility) (Fixed -- Implemented the AreaZone system. Concentration AoE spells now create persistent zones that: [1] damage enemies at start of their turn if inside the zone, [2] damage enemies when they move into the zone, [3] move with the caster [follows_caster=True], [4] auto-remove when concentration ends. Per-round tracking prevents double damage. Zone creation happens automatically in execute_effect() for concentration + area + saving_throw actions.)
-Spirit guardians has no visual component; originally out of scope, but would be helpful for players (Fixed -- Added zone painter system. Active zones render as semi-transparent hex overlays on the grid. Player zones are blue-tinted, enemy zones are red-purple. Rendered as the bottom-most overlay layer, below movement and attack range indicators.)
-Spirit guardians also harms the caster (Fixed -- _resolve_effect_targets() unconditionally re-inserted clicked_target_id even when it was the caster. Added check to skip re-insertion if clicked_target_id == combatant.creature_id.)
-Spirit guardians appears to have the correct range
-Poison damage works correctly on enemies who have immunity, as well as those who don't

User notes on encounter 8:
-Stress test handled well
-Some pathing issues with gargantuan enemies - likely unfixable. It makes sense that something of a large size has difficulty walking around.
-Water does water related things correctly

Need to think of edge cases that currently haven't been tested for further scenarios (moonbeam, Wildshape, summon familiars, etc.).

---

#	Encounter	Grid	Party	Enemies	Primary Tests
9	Moonbeam Arena	20×15	Willow + Elara	4 Hobgoblins	Click-to-place AoE, AoE preview overlay, movable zones, fixed-center zones
10	Summoner Showdown	18×12	Finn + Willow	2 Bandits + 2 Wolves	Summon familiar, Wild Shape, summon initiative, summon death/revert
11	Temp HP Gauntlet	16×12	Morgana + Brother Aldric	3 Orcs + 2 Skeletons	Temporary HP granting, no-stack rule, temp HP absorption

New characters created for scenarios 9-11:
- Willow Thornroot (characters/willow.json) -- Wood Elf Druid 5 (Circle of the Moon). Moonbeam, Flaming Sphere, Wild Shape (Bear), Healing Word, Produce Flame, Scimitar.
- Finn Whisperwind (characters/finn.json) -- Halfling Wizard 5 (School of Conjuration). Find Familiar (Owl), Fire Bolt, Magic Missile, Dagger.
- Morgana Frostweaver (characters/morgana.json) -- Tiefling Warlock 5 (The Fiend). Eldritch Blast, Armor of Agathys (10 temp HP), False Life (1d4+4 temp HP), Hellish Rebuke, Hex, Dagger.

New monster sheets created:
- Brown Bear (monsters/brown_bear.json) -- Large beast, CR 1. Bite (1d8+4) and Claws (2d6+4). Wild Shape target for Willow.
- Owl (monsters/owl.json) -- Tiny beast, CR 0. Talons (1 damage). Familiar target for Finn.

New features implemented to support these scenarios:
- Click-to-Place AoE: Area spells (Moonbeam, Fireball, etc.) now target a hex on the grid rather than the caster's position. Gold hex preview overlay shows blast radius while hovering.
- Fixed-Center Zones: Moonbeam/Flaming Sphere create persistent zones at the clicked hex (not following the caster). Spirit Guardians backward-compatible (still follows caster).
- Movable Zones: Moonbeam can be repositioned as an action; Flaming Sphere as a bonus action. "Move Zone" button appears in radial menu when applicable.
- Temporary HP Granting: Actions can grant temp HP via dice expression (e.g., "10" or "1d4+4"). 5e no-stack rule enforced (higher value kept).
- Summon Creature: Actions can reference a creature JSON file to summon onto the battlefield. Summoned creature joins same team, acts after summoner in initiative.
- Wild Shape: Variant of summoning where 0 HP reverts to the original creature (with original HP) instead of removing the summon.
- Builder UI: New fields added to Actions tab -- Temp HP (TextInput), Zone Move Cost (Dropdown), Summon Creature (TextInput path), Wild Shape (Checkbox).

Scenario 9 test steps:
1. Cast Moonbeam (Willow): Select Moonbeam, hover over grid -- verify gold hex preview shows 5-ft radius. Click a hex near hobgoblins -- verify zone placed at clicked hex (blue overlay), NOT on Willow. User notes: Verified
2. Move Willow away from the zone -- verify zone stays at original hex (fixed-center, not follows_caster). User notes: Verified
3. Next turn, click "Move Zone" in radial menu -- verify targeting mode activates. Click new hex -- verify zone center moves, entry damage triggers on any enemies now inside. User notes: after the fix, verified it functions as expected.
4. Have an enemy break Willow's concentration (or voluntarily drop it) -- verify Moonbeam zone vanishes from the grid. User notes: Verified
5. Cast Flaming Sphere (Willow): Verify zone placed at clicked hex. On same turn, move sphere as bonus action (zone_move_cost="bonus_action"). User notes: Verified
6. Have Elara cast Fireball at a hex -- verify instant AoE damage to all creatures in radius, NO persistent zone created (Fireball is not concentration). User notes: Verified
7. Verify action economy: casting Moonbeam consumes action, moving Moonbeam consumes action, moving Flaming Sphere consumes bonus action. User notes: Verified

Scenario 10 test steps:
1. Finn casts Find Familiar (Owl): Select the action, click an empty hex within range -- verify owl token appears on that hex, on player team, with owl stats (1 HP, AC 11). User notes: Verified
2. Check initiative order -- verify owl acts immediately after Finn (same initiative roll, lower tiebreaker). User notes: Verified.
3. Try to place a summon on an occupied hex -- verify placement is blocked. User notes: Verified.
4. On owl's turn, use Talons attack on an enemy -- verify attack resolves normally. User notes: After fixing, verified.
5. Have an enemy kill the owl (1 HP) -- verify owl is removed from combat entirely (no death saves for summons). User notes: Verified.
6. Finn summons another owl -- verify it gets a unique ID (not conflicting with the first). User notes: Not sure how I would verify a unique ID, but a fresh owl spawned with no issues.
7. Willow uses Wild Shape (Bear): Select the action, click adjacent hex -- verify brown bear token appears with bear stats (34 HP, AC 11, Large size, Bite/Claws actions). User notes: Verified, although Willow is not removed from the turn order.
8. Deal enough damage to drop the bear to 0 HP -- verify Willow reverts to her original form with her original HP at the bear's position. User notes: After fixing, verified.
9. After reverting, verify Willow has her original actions (Moonbeam, Scimitar, etc.) again. User notes: After fixing, verified.
Final user notes: Finn can summon a new owl every turn, while the old one persists. Willow is not removed from the turn order when she Wildshapes; you have to manually skip her turn every time right before the bear is allowed to act. Despite this, both systems now work quite well. <-- These were addressed. RAW allows unlimited summoning based on spell slot limits. Tool was patched so that Willow's turn is now skipped.

Scenario 11 test steps:
1. Morgana casts Armor of Agathys (self-target): Verify 10 temporary HP granted, visible in creature info panel as temp HP. User notes: Verified after UI addition.
2. An orc attacks Morgana -- verify temp HP absorbs damage first (real HP untouched until temp HP depleted). User notes: Verified.
3. After some temp HP is lost, Morgana casts False Life (1d4+4): If the roll is LESS than remaining temp HP, verify old value is kept (no-stack rule). If the roll is HIGHER, verify new value replaces old. User notes: Verified after addition of UI.
4. Multiple enemies attack Morgana in sequence -- verify temp HP depletes correctly across multiple hits, then real HP takes over. User notes: Verified.
5. After temp HP is fully depleted, verify subsequent damage goes directly to real HP. User notes: Verified.
6. Brother Aldric uses a healing spell on Morgana -- verify healing restores real HP (does not interact with temp HP). User notes: Verifed after UI addition.

---

#	Encounter	Grid	Party	Enemies	Primary Tests
12	Dragon Throne Room	25×20	Ser Marcus + Valeria + Elara + Aldric	Adult Blue Dragon	Legendary action point pool, AI legendary decisions, AoE legendary (Wing Attack), initiative badge
13	Vampire's Sanctum	18×14	Ser Marcus + Thorin	Vampire Lord (player-ctrl) + 2 Skeletons	Player-controlled legendary popup, pass/use decisions, multi-cost legendary actions

New monster sheets created for scenarios 12-13:
- Adult Blue Dragon (monsters/adult_blue_dragon.json) -- Huge dragon, CR 16. AC 19, 225 HP. Lightning immunity. Bite (2d10+7 piercing + 1d10 lightning, 10 ft reach), Claw (2d6+7 slashing), Lightning Breath (12d10 lightning, 90-ft line, DC 19 DEX save, half on success), Frightful Presence (DC 17 WIS, frightened). Legendary action count: 3. Legendary actions: Detect (1 pt, self -- no combat effect), Tail Attack (1 pt, 2d8+7 bludgeoning, 15 ft reach), Wing Attack (2 pts, DC 20 DEX save, 2d6+7 bludgeoning + prone, 10-ft radius AoE).
- Vampire Lord (monsters/vampire_lord.json) -- Medium undead, CR 13. AC 16, 144 HP. Resistance to necrotic/bludgeoning/piercing/slashing. Unarmed Strike (1d8+4 bludgeoning), Bite (1d6+4 piercing + 3d6 necrotic), Charm (DC 17 WIS, charmed). Legendary action count: 3. Legendary actions: Move (1 pt, self -- no combat effect), Unarmed Strike (1 pt, 1d8+4 bludgeoning), Bite (2 pts, 1d6+4 piercing + 3d6 necrotic).

Scenario 12 -- Dragon Throne Room -- is designed to test AI-controlled legendary actions. The dragon is AI-controlled (use_ai_for_enemies=true) so the tester can observe whether the AI correctly uses legendary actions between player turns without manual intervention.

Scenario 13 -- Vampire's Sanctum -- is designed to test player-controlled legendary actions. The vampire AND skeletons are all player-controlled (use_ai_for_enemies=false) so the tester manually exercises the legendary action popup, choosing actions or passing. This also tests legendary actions with a medium-size creature and multiple cost tiers.

Scenario 12 test steps:
1. Load the encounter and roll initiative. Verify the Adult Blue Dragon's initiative panel entry shows a purple "L:3" badge indicating 3 legendary action points. User notes: Verified.
2. End a player character's turn. Verify the legendary action phase triggers: the dragon should get an opportunity to use a legendary action. Since the dragon is AI-controlled, the AI should automatically decide to use or pass on a legendary action. Observe whether the AI uses Tail Attack or Wing Attack if a player is in range. User notes:Verified after fix.
3. After the dragon uses a legendary action, verify the initiative badge updates (e.g., L:2 after spending 1 point, or L:1 after spending 2 points). User notes: Verified.
4. End another player character's turn. The dragon should get another legendary action opportunity with its remaining points. Verify the AI makes a sensible decision (uses an action if affordable, passes if not). User notes: Verified, and uses appropriate action.
5. Continue ending player turns until the dragon has 0 points remaining. Verify the dragon does NOT get a legendary action popup/opportunity when it has 0 points. User notes: Verified.
6. Advance to the dragon's own turn. At the START of the dragon's turn, verify the legendary point pool resets to 3 (initiative badge shows L:3 again). User notes: Verified.
7. On the dragon's own turn, use its normal actions (Bite, Claw, Lightning Breath). Verify that legendary actions do NOT appear in the dragon's normal action menu -- legendary actions are out-of-turn only. User notes: The players cannot see the dragon's menu. However, verified that during its normal turn it does not use legendary actions. Lightning breath is almost an automatic party wipe (lol).
8. End the dragon's own turn. Verify that the dragon is NOT offered a legendary action at the end of its OWN turn (per 5e rules: can't use legendary actions on your own turn). The next player's turn should begin immediately. User notes: Verified based on the dragon's actions.
9. Repeat for 2-3 full rounds. Verify points reset reliably each round and the legendary action flow doesn't hang or skip turns. User notes: Verified.
10. (Edge case) If the dragon kills a player character with a legendary action, verify combat does not crash or hang. Victory should be checked after legendary action resolution. User notes: Technically no victory screen as the party is making saving rolls even though all of them are down. Indicates a potential problem with the death save system. Not a priority, as the players will know that the encounter is over and can gracefully back out.
11. (Edge case) If all players are defeated during a legendary action, verify combat ends correctly with the enemy as the winner. User notes: Same as above.

Scenario 13 test steps:
1. Load the encounter. Verify the Vampire Lord's initiative panel entry shows "L:3". The skeletons should NOT have legendary badges. User notes: Verified.
2. When a non-vampire creature's turn ends, a legendary action popup should appear for the Vampire Lord. Verify the popup shows: creature name ("Lord Strahd"), remaining points, available actions with their costs (Move 1pt, Unarmed Strike 1pt, Bite 2pts), and a "Pass" button. User notes: Verified.
3. Click "Pass" on the popup. Verify no points are spent and the next creature's turn begins normally. User notes: Verified.
4. On the next legendary opportunity, select "Unarmed Strike (Legendary)" from the popup. If the action requires a target, verify you enter target selection mode -- click on an enemy within range to execute the attack. Verify 1 point is deducted (L:2). User notes: Verified, although you can waste your LP on enemies not within range.
5. On the next opportunity, select "Bite (Legendary)" (costs 2 points). Verify 2 points are deducted (L:0). User notes: Verified.
6. After spending all 3 points, verify no more legendary action popups appear for the rest of the round. User notes: Verified after fix.
7. When the vampire's own turn starts, verify the pool resets to 3. User notes: Verified.
9. Test clicking outside the popup or pressing Escape. Both should count as "Pass". User notes: Verified.
10. (Edge case) After a skeleton's turn ends, verify the vampire gets a legendary opportunity. After the vampire's OWN turn ends, verify it does NOT get a legendary opportunity. After a player's turn ends, verify the vampire DOES get a legendary opportunity. User notes: Verified.

---

#	Encounter	Grid	Party	Enemies	Primary Tests
14	Volcanic Lair	20x15	Marcus + Elara + Aldric	Young Red Dragon	AI-controlled lair actions, lair initiative at 20 (loses ties), gold lair entry in initiative panel, saving throws (DEX/STR/CON), half-damage-on-success, no-repeat consecutive round rule, damage+condition combo (Tremor: prone)
15	Cursed Crypt	18x14	Marcus + Thorin	Vampire Lord (player-ctrl) + 2 Skeletons	Player-controlled lair action popup, pass button, consecutive-round filtering, lair + legendary interleaving, damage+condition combo (Grasping Graves: restrained)

No new characters or monsters needed -- these scenarios reuse existing sheets.

New features implemented to support these scenarios:
- Lair Actions (Encounter-Level): Encounters can now have lair actions -- location-based effects that fire at initiative count 20, losing all ties. Lair actions are stored on the Encounter model (not on any creature). A pseudo-combatant "__lair__" appears in the initiative order. Each round, only one lair action fires, and the same action cannot be used two consecutive rounds.
- Encounter Editor Integration: "Has Lair" checkbox and "Edit Lair Actions" button added to the encounter setup screen. The lair action editor popup allows adding/removing/editing lair actions (name, description, save ability, DC, damage dice, damage type, half-on-success toggle).
- AI Lair Planning: When use_ai_for_enemies=true, AI automatically selects the best lair action based on estimated damage x number of player targets x priority scoring. When use_ai_for_enemies=false, a gold-themed popup lets the DM choose an action or pass.
- Combat Resolution: Lair actions resolve saving throws per-target directly (no "user" creature). Supports damage-on-fail, half-damage-on-success, and no-damage-on-success.

Scenario 14 -- Volcanic Lair -- is designed to test AI-controlled lair actions. The dragon and lair are both AI-controlled (use_ai_for_enemies=true) so the tester observes lair actions resolving automatically between turns. Three different lair actions test different save abilities (DEX, STR, CON) and damage behaviors (half on success vs none on success).

Scenario 15 -- Cursed Crypt -- is designed to test player-controlled lair actions AND the interaction between lair actions and legendary actions in the same encounter. The Vampire Lord has legendary actions, and the crypt has lair actions. All enemies are player-controlled (use_ai_for_enemies=false) so the tester manually exercises both the lair action popup and legendary action popup, observing how they interleave.

Scenario 14 test steps:
1. Load the encounter and roll initiative. Verify the initiative panel shows a gold "Lair (20)" entry with a gold diamond icon. It should appear at initiative 20, AFTER any creature that also rolled 20 (lair loses all ties). User notes: Verified.
2. Play through turns until the lair entry becomes current (gold highlight, "> Lair (20)"). Since the AI controls the lair, the AI should automatically select a lair action and resolve it. Verify the combat log shows the lair action name and saving throw results for each player character. User notes: Verified.
3. After the lair action resolves, verify the lair turn ends automatically and combat advances to the next creature's turn. The lair should NOT consume any creature's action economy. User notes: Verified.
4. Observe the damage: if Magma Eruption was used (DEX save DC 15, 2d6 fire, half on success), verify that players who failed the save took full damage and players who succeeded took half. If Tremor was used (STR save DC 14, 1d10 bludgeoning, none on success), verify that players who succeeded took zero damage. User notes: Verified.
5. Play through an entire round and into the next lair turn. Verify that the AI does NOT repeat the same lair action used last round (consecutive-round restriction). For example, if Magma Eruption was used in round 1, only Tremor and Toxic Fumes should be available in round 2. User notes: Verified.
6. Continue for 3+ rounds. Verify the lair action fires once per round at initiative 20, the no-repeat rule cycles correctly, and combat does not hang or crash on the lair turn. User notes: Verified.
7. (Edge case) If a player character is knocked unconscious before the lair turn, verify the lair action does NOT target unconscious creatures (it should only target conscious player-side creatures). User notes: Verified.
8. (Edge case) If all player characters are defeated, verify combat ends with enemy victory (the lair pseudo-combatant should not prevent victory detection). User notes: Does not work due to a bug with death saving throws. Not a priority to fix at the moment. Considering this passable for now.

Scenario 15 test steps:
1. Load the encounter and roll initiative. Verify the initiative panel shows BOTH a gold "Lair (20)" entry AND a purple "L:3" badge on Lord Strahd's initiative entry. Skeletons should have neither. User notes: Verified.
2. When the lair turn arrives (initiative 20), a gold-themed lair action popup should appear (since use_ai_for_enemies=false). Verify the popup shows the available lair actions: "Grasping Graves" and "Unholy Darkness", plus a "Pass" button. User notes: Verified.
3. Click "Pass" on the lair popup. Verify no lair action fires, the combat log shows "No lair action used this round", and the next creature's turn begins. User notes: Verified.
4. Play through to the next lair turn (round 2). Select "Grasping Graves" from the popup. Verify the saving throw resolves against all conscious player characters (DEX save DC 15, 2d6 necrotic, half on success). User notes: Verified.
5. Play through to round 3's lair turn. Verify "Grasping Graves" is NOT available in the popup (it was used last round). Only "Unholy Darkness" should appear. Select it and verify it resolves correctly (CON save DC 14, 3d4 necrotic, none on success). User notes: Verified.
6. Play through to round 4's lair turn. Verify "Grasping Graves" is available again (it was NOT used in round 3). Both actions should appear in the popup. User notes: Verified.
7. Verify lair + legendary interleaving: after a non-Strahd creature's turn ends, the LEGENDARY action popup should appear for Lord Strahd (if he has points remaining). The LAIR action popup should only appear when the lair entry is current at initiative 20 -- NOT after every turn. These are two separate systems. User notes: Verified. Important to note, the lair turn ending does activate Strahd's legendary actions. I assume this is unintended. Also, there is a new issue with the camera: when clicking anything relating to lair actions, the left click camera scroll is stuck. It can be unstuck by clicking again so not a huge issue, but this has caused accidental player actions in the tool. Could be related to lair actions accepting input on mouse down and not mouse up; not sure how this is implemented.
8. (Edge case) Click outside the lair popup or press Escape. Verify this counts as "Pass" (same behavior as the legendary popup). User notes: Verified.
9. (Edge case) Verify the lair turn and Strahd's legendary action phase are independent: spending legendary action points does NOT affect lair actions, and using a lair action does NOT consume Strahd's legendary points. User notes: Verified.

Bugs found and fixed during scenarios 14-15 playtesting:
- Lair turn ending triggered legendary action phase for Lord Strahd (Fixed -- end_turn() now captures was_lair_turn flag before resetting and skips legendary queue when the lair turn just ended, per 5e rules)
- Camera drag stuck after clicking lair popup (Fixed -- MOUSEBUTTONDOWN was forwarded to grid view even when popup consumed the click, starting a drag that never received MOUSEBUTTONUP. Now only forwards camera events when popup does NOT consume the click. Same fix applied to legendary popup)

---

#	Encounter	Grid	Party	Enemies	Primary Tests
16	Fey Grove	16x12	Marcus + Elara + Thorin	Mage (Grove Keeper) + 2 Wolves	Expanded lair effects: condition-only (restrained), damage+condition combo (cold+prone), healing enemies, temp HP for enemies, summoning reinforcements, AI scoring for all effect types

No new characters or monsters needed -- this scenario reuses existing sheets.

New features implemented to support this scenario:
- Condition-Only Lair Actions: Lair actions can now apply conditions (restrained, prone, etc.) on failed saves without dealing any damage. The lair action editor now includes a ListEditor for selecting conditions from a curated list.
- Damage + Condition Combo: Lair actions can deal damage AND apply conditions on the same failed save. On a successful save, half damage applies (if configured) but conditions are NOT applied.
- Lair Healing: Lair actions can heal all conscious enemy-side creatures using a dice expression (e.g., "2d6"). Players are not affected.
- Lair Temporary HP: Lair actions can grant temporary HP to all conscious enemy-side creatures. Follows the 5e no-stack rule (only replaces if new value is higher).
- Lair Summoning: Lair actions can summon a creature from a JSON file. The summoned creature is auto-placed on an empty hex near existing enemies, joins the enemy team, and is inserted into initiative right after the lair entry. The creature is player-controlled or AI-controlled based on the encounter's use_ai_for_enemies flag.
- Editor Updates: The lair action editor popup now supports all new effect types with dedicated text input fields for healing dice, temp HP dice, and summon creature path. Damage fields are now optional (can be left empty for condition-only or non-save actions).
- AI Scoring: AI lair action scoring now considers condition value (paralyzed > stunned > restrained > prone), healing value, temp HP value, and summoning value. Fixes a bug where AI checked the wrong field for conditions.

Scenario 16 -- Fey Grove -- is designed to test all new lair action effect types in a single AI-controlled encounter. The grove has five lair actions, each exercising a different effect type: condition-only, damage+condition combo, healing, temp HP, and summoning. The AI should intelligently select between these based on the current combat state.

Scenario 16 test steps:
1. Load the encounter and roll initiative. Verify the initiative panel shows a gold "Lair (20)" entry. The Grove Keeper and two Fey Wolves should be on the enemy team. User notes: Verified.
2. Play through to the first lair turn. The AI should select one of the five lair actions. Observe which action the AI chooses and verify it resolves correctly based on its type. User notes: Verified. New lair actions seem to work as intended.
3. If "Grasping Roots" was used (condition-only): Verify STR save DC 14. On failure, player should gain the "restrained" condition. On success, NO effect at all (no damage, no condition). Verify restrained condition shows in the creature info panel and that the creature can attempt a save to end it at end of their turn. User notes: Verified.
4. If "Freezing Wind" was used (damage+condition combo): Verify CON save DC 13, 2d6 cold damage on fail, half damage on success. On failure, player should ALSO gain the "prone" condition. On success, half damage but NO prone condition. User notes: Verified.
5. If "Nature's Mending" was used (healing): Verify that all conscious enemy creatures (Grove Keeper, Fey Wolves) are healed for 2d6 HP. Verify that NO player characters are healed. If all enemies are at full HP, the healing should have no visible effect (HP capped at max). User notes: Verified.
6. If "Fey Ward" was used (temp HP): Verify that all conscious enemy creatures gain 8 temporary HP. Verify the temp HP appears in their creature info panel. If an enemy already has more than 8 temp HP, verify the existing higher value is kept (5e no-stack rule). User notes: Verified.
7. If "Call of the Wild" was used (summoning): Verify a new Wolf token appears on the grid near the existing enemies. The wolf should be on the enemy team, appear in the initiative order (right after the lair entry), and have standard wolf stats. Verify the combat log shows "The lair summons Wolf!" User notes: Verified. Two wolves were even spawned at one point, with no issue.
8. Continue playing for 3+ rounds. Verify the no-repeat consecutive round rule applies: the same lair action should not be used in two consecutive rounds. Verify the AI cycles through different effect types. User notes: Verified.
9. Damage an enemy creature, then observe whether the AI chooses "Nature's Mending" on a subsequent lair turn (it should prefer healing when allies are wounded). User notes: Verified, after fix.
10. If a wolf was summoned, verify it takes normal turns (moves, attacks) and can be killed. If killed, verify it is removed from combat and initiative like any normal creature. User notes: Verified.
11. (Edge case) If multiple wolves are summoned across different rounds, verify each gets a unique ID and occupies its own hex. User notes: It does occupy its own hex, not sure how to verify unique ID. Regardless, from a player standpoint the wolves that are summoned function as intended.
12. (Edge case) Open the lair action editor from the encounter setup screen. Verify the new fields appear: Conditions list (with picker), Heal Enemies text field, Grant Temp HP text field, Summon creature path field. Verify editing and saving these fields preserves data correctly. User notes: The UI might be currently insufficient for creating lair actions from a user view (ie certain elements of the system aren't exposed to the user). Need to workshop this a bit.

---

#	Encounter	Grid	Party	Enemies	Primary Tests
17	Arcane Escape	18×14	Elara + Brother Aldric	Mage + 3 Hobgoblins	Self-teleport (Misty Step), teleport range, OA bypass, spell slot cost, AI teleport, teleport visual, teleport into zone
18	Thunderclap Transit	20×15	Lyra Stormcaller + Ser Marcus	4 Orcs	Thunder Step origin damage, CON saves, half on success, origin AoE radius, 90-ft range, both teleport types on one character
19	Dimensional Rescue	25×20	Lyra + Thorin + Shade	2 Ogres + 2 Hobgoblins	Dimension Door 500-ft range, passenger mechanic, passenger placement, solo teleport, wall/occupied hex rejection, long-distance visual

New characters created for scenarios 17-19:
- Lyra Stormcaller (characters/lyra.json) -- Half-Elf Sorcerer 7 (Draconic Bloodline, Red). Fire Bolt (cantrip), Thunder Step (action, 90 ft teleport, 3d10 thunder origin damage, CON DC 15), Dimension Door (action, 500 ft teleport, passenger), Misty Step (bonus action, 30 ft teleport), Dagger. Fire resistance. Spell slots: 1 (4), 2 (3), 3 (3), 4 (1).

Existing characters updated:
- Elara Nightwhisper -- Misty Step bonus action updated with teleport_range=30 and teleport_self=true fields (was previously missing teleport system fields).
- Brother Aldric -- Misty Step bonus action already had teleport fields from prior implementation.
- Mage (monster) -- Misty Step bonus action updated with teleport_range=30 and teleport_self=true fields.

New features implemented to support these scenarios:
- Teleportation System: Actions can now teleport the caster to a target hex. Three variants: self-teleport (Misty Step: bonus action, 30 ft), origin damage (Thunder Step: action, 90 ft, damages enemies at departure point), and passenger (Dimension Door: action, 500 ft, adjacent willing ally comes along).
- Teleport fields on Action model: teleport_range (max distance in feet), teleport_self (caster teleports), teleport_passenger (bring adjacent ally), teleport_origin_effect (damage dice at origin), teleport_origin_damage_type (damage type for origin AoE).
- Combat Manager: execute_teleport(target_hex, passenger_id) bypasses movement costs, opportunity attacks, and pathfinding. Validates range, passability, and occupancy. Handles origin damage (saving throws per enemy in area_size), passenger relocation, concentration, zone entry at destination.
- Visual Effect: TeleportEffect renders contracting cyan ring at origin + expanding ring at destination (600ms, arcane cyan-blue color).
- AI Support: AI scores teleport actions based on escape value (low HP = higher priority), repositioning (melee vs ranged preference), and origin damage bonus. New TurnStepType.EXECUTE_TELEPORT.
- Builder UI: Teleportation section in Actions tab with range spinner, self/passenger checkboxes, origin effect/damage type fields.
- Event System: TELEPORT and FORCED_MOVEMENT event types added to CombatEventType, with sound and color mappings.

Scenario 17 -- Arcane Escape -- tests the most common teleportation case: Misty Step. Both player characters (Elara and Aldric) have Misty Step, and the enemy Mage also has Misty Step. This allows testing player-controlled teleportation, AI-controlled teleportation, and the interaction between teleportation and Spirit Guardians zones. The hobgoblins start flanking the party, creating pressure for the squishy wizard to teleport away. A central wall cluster forces tactical movement and makes teleportation valuable for repositioning.

Scenario 17 test steps:
1. Load the encounter and roll initiative. Verify all combatants appear on the grid: Elara and Aldric near center-left, Mage at top-right, three hobgoblins flanking from multiple directions. User notes: Verified.
2. On Elara's turn, select Misty Step from the bonus action menu. Verify targeting mode activates: the grid should show a cyan hex overlay highlighting all valid destination hexes within 30 feet (6 hexes). Wall hexes and occupied hexes should NOT be highlighted. User notes: Verified.
3. Click a valid destination hex within the cyan overlay. Verify Elara teleports to that hex: her token disappears from the origin and reappears at the destination. Verify a cyan ring visual effect plays (contracting at origin, expanding at destination). User notes: Verified.
4. Verify the combat log shows a TELEPORT event with "from" and "to" hex coordinates. Verify the bonus action slot is consumed (Misty Step is no longer available this turn). User notes: It shows that Elara used misty step. It did not contain coordinates. This is okay. Verified partially.
5. Check that a 2nd-level spell slot was consumed. Verify Elara can still use her action (Fire Bolt, Fireball, etc.) on the same turn after Misty Step. User notes: Verified.
6. Position Elara adjacent to a hobgoblin. On her next turn, use Misty Step to teleport away. Verify that NO opportunity attack is triggered by the hobgoblin -- teleportation bypasses OAs entirely. User notes: Verified.
7. On Brother Aldric's turn, cast Spirit Guardians first (action), creating a radiant zone around him. Then on his next turn, use Misty Step (bonus action) to teleport. Verify the Spirit Guardians zone follows Aldric to his new position (zone_follows_caster=true). User notes: Verified.
8. Observe the enemy Mage's AI behavior. If a player moves adjacent to the Mage (melee range), the Mage should consider using Misty Step to escape. Verify the AI teleports the Mage to safety and the visual effect plays for the AI-controlled teleport. User notes: The mage cast a fireball on the enemy right next to him (Brother Aldric), then took damage attempting to escape due to attack of opportunity. Seems he had a bonus action available to cast misty step.
9. Attempt to teleport to an occupied hex (e.g., where a hobgoblin stands). Verify the destination is rejected -- the hex should not be highlighted in the cyan overlay, or clicking it should have no effect. User notes: Verified.
10. Attempt to teleport to a wall hex (the central wall cluster). Verify the wall hexes are not valid destinations. User notes: Verified.
11. Attempt to teleport beyond 30-ft range (7+ hexes away). Verify those hexes are NOT highlighted in the cyan overlay and clicking them has no effect. User notes: Verified.
12. With Aldric's Spirit Guardians active, have Elara teleport INTO the Spirit Guardians zone (destination hex within the zone). Verify Elara is NOT damaged (Spirit Guardians only harms enemies). Then position the enemy Mage such that it could teleport into the Spirit Guardians zone -- observe whether zone entry damage triggers on an enemy teleporting in. User notes: Verified with a caveat. I cannot get the enemy mage to teleport, and even less likely would I be able to line it up in such a way that he would teleport into spirit guardian.
13. (Edge case) Use all of Elara's 2nd-level spell slots on Misty Step and other spells. Verify Misty Step becomes unavailable (grayed out or not selectable) when no spell slots remain. User notes: Verified.
14. (Edge case) Cancel a teleport in progress (press Escape or right-click during targeting). Verify the cyan overlay disappears, no spell slot is consumed, and normal turn flow resumes. User notes: Verified.

Scenario 18 -- Thunderclap Transit -- tests Thunder Step's unique origin damage mechanic. Lyra has both Thunder Step (action, 90 ft, 3d10 thunder origin damage) and Misty Step (bonus action, 30 ft). The orcs are aggressive melee fighters who will rush to surround her, making Thunder Step's "teleport away and punish everyone at the departure point" mechanic ideal to test.

Scenario 18 test steps:
1. Load the encounter and roll initiative. Verify Lyra and Ser Marcus are positioned center-left. Four orcs should be spread across the right side. User notes:
2. Let the orcs advance toward the party (they have the Aggressive trait -- bonus action to move toward enemies). Wait until at least 2 orcs are adjacent to Lyra. User notes: Verified.
3. On Lyra's turn, select Thunder Step from the action menu. Verify targeting mode activates with a cyan hex overlay showing valid destinations within 90 feet (18 hexes). This range should cover most of the grid. User notes: Verified.
4. Click a valid destination far from the orcs. Verify Lyra teleports to the destination hex. Verify the teleport visual effect plays. User notes: Verified.
5. After teleportation, verify origin damage resolves: each enemy within 10 feet (2 hexes) of Lyra's ORIGINAL position must make a CON saving throw (DC 15). Check the combat log for saving throw results and damage amounts. User notes: Verified. Noted that my ally did not take damage (which I assume is desired behavior for this spell).
6. Verify damage values: enemies who FAIL the save should take full 3d10 thunder damage. Enemies who SUCCEED should take HALF damage (rounded down). This is the "damage_on_success: half" behavior. User notes: Verified.
7. Verify that orcs who were NOT within 10 feet of Lyra's original position are completely unaffected -- no saving throw, no damage. User notes: Verified.
8. Verify that a 3rd-level spell slot was consumed (Thunder Step costs spell_slot_3). Verify Lyra's action is consumed -- she cannot use another action this turn. User notes: Verified. This did show me that there was some sort of weird behavior with the off hand weapon bonus attack. We will revisit that at some other time.
9. On Lyra's next turn, verify she can use BOTH Thunder Step (action) and Misty Step (bonus action) if she has spell slots. These are separate action types that don't conflict. User notes: Verified, and actually hilarious to misty step next to someone, then Thunder Step away to wipe out like three people.
10. Use Misty Step on the same turn as a different action (e.g., Fire Bolt + Misty Step). Verify that Misty Step consumes only the bonus action and a 2nd-level slot, while Fire Bolt consumed the action. User notes:
11. Compare the two teleport ranges visually: select Misty Step and observe the cyan overlay (30 ft / 6 hexes), then cancel and select Thunder Step and observe the overlay (90 ft / 18 hexes). The Thunder Step overlay should cover dramatically more of the grid. User notes:
12. (Edge case) Use Thunder Step when NO enemies are within 10 feet of Lyra's position. Verify the teleport succeeds normally but no origin damage is dealt (no saving throws rolled). User notes: Verified.
13. (Edge case) Use Thunder Step with only Ser Marcus (ally) adjacent to Lyra. Verify that Ser Marcus is NOT affected by origin damage -- Thunder Step only damages enemies within the AoE, not allies. User notes: Verified and noted above.
14. (Edge case) Exhaust all 3rd-level spell slots. Verify Thunder Step becomes unavailable while Misty Step (2nd-level) may still be usable if 2nd-level slots remain. User notes: Verified.

Scenario 19 -- Dimensional Rescue -- tests Dimension Door's long-range teleportation and passenger mechanic on a large 25×20 grid. Shade is trapped behind a wall of stone in the fortress's eastern wing. Lyra must use Dimension Door to teleport through the walls to reach Shade, then bring her back as a passenger. The large grid ensures 500-ft range is properly exercised.

Scenario 19 test steps:
1. Load the encounter and roll initiative. Verify the grid layout: Lyra and Thorin start on the west side (left), Shade is trapped behind walls on the east side (right), ogres and hobgoblins patrol the middle. The wall formation should create an enclosed area around Shade. User notes: Verified.
2. Observe that Shade is physically inaccessible via normal movement -- the wall hexes block all paths to her position. Confirm this by selecting Shade's turn and checking that no movement path reaches the allies. User notes: The walls were not created in the original scenario to cut off shade totally. However, the character is still extremely difficult to get to with the current placement (120ft or so of travel around the walls). I believe this fits the purpose of the scenario.
3. On Lyra's turn, select Dimension Door from the action menu. Verify the cyan overlay shows valid destinations within 500 feet. On a 25×20 grid (each hex = 5 ft), this is 100 hexes -- essentially the ENTIRE grid should be highlighted except walls and occupied hexes. User notes: Verified.
4. Click a hex inside the walled prison area, adjacent to Shade (e.g., [19, 7] or [20, 8]). Verify Lyra teleports through the walls to that hex -- teleportation ignores line of sight and terrain. User notes: Verified.
5. Verify the teleport visual effect plays across the long distance (cyan rings at origin and destination). User notes: Verified.
6. After teleporting, verify Lyra is now adjacent to Shade inside the walled area. On Lyra's next turn, select Dimension Door again. This time, a passenger prompt or selection should be available. Select Shade as the passenger. User notes: Verified.
7. Click a destination hex back on the west side of the map near Thorin. Verify BOTH Lyra and Shade teleport: Lyra lands on the clicked hex, and Shade should appear on an adjacent hex near the destination. User notes: Verified.
8. Verify Shade's position after passenger teleport: she should be within 1 hex of Lyra's destination, on an empty and passable hex. User notes: Verified.
9. Verify that only ONE spell slot was consumed for the Dimension Door that transported both Lyra and Shade. The passenger comes along for free. User notes: Verified.
10. Test solo Dimension Door (no passenger): on another turn, use Dimension Door without selecting a passenger. Verify Lyra teleports alone. User notes: Verified.
11. Attempt to use Dimension Door to teleport to a wall hex inside the fortress. Verify the destination is rejected (walls are impassable, even for teleportation). User notes: Verified.
12. Attempt to teleport to a hex occupied by an ogre. Verify the destination is rejected. User notes: Verified.
13. Have Thorin engage the ogres in melee while Lyra performs the rescue. Verify the ogres' AI focuses on Thorin (the visible threat) and doesn't somehow path through the walls to reach Shade. User notes: Verified, kind of. They walls aren't actually to the edge of the map, so they can path to Shade after quite a distance. Enemies near Thorin still prioritize him, if getting to Thorin is faster than getting to Shade. No impassable objects are directly pathed over.
14. (Edge case) Try to select an enemy creature as a Dimension Door passenger. Verify this is not allowed -- only willing allies (same team) should be valid passengers. User notes: Verified.
15. (Edge case) Try to use Dimension Door when Lyra has no 4th-level spell slots remaining. Verify it is unavailable. Misty Step (2nd-level) should still work if 2nd-level slots remain, but has only 30-ft range. User notes: Verified.
16. (Edge case) Use Dimension Door to a hex where there are no adjacent empty hexes for the passenger. Observe how the system handles this -- the passenger should either be placed on the best available nearby hex or the teleport should be adjusted. User notes: There are no areas like this on this current map. This is such an edge case that I think we are good for now.

---

#	Encounter	Grid	Party	Enemies	Primary Tests
20	The Precipice	16x12	Morgana + Willow	3 Orcs	Push on ranged attack hit (Repelling Blast), pull on ranged attack hit (Thorn Whip), push stopped by wall, push to grid edge, Shove tactic (push 5ft + prone), forced movement visual effects
21	Storm Front	18x14	Elara + Thorin	Cultist Warlock + 2 Hobgoblins	AoE push on failed save (Thunderwave), no push on save success, AI Repelling Blast push, Shove contested Athletics check, shove prone for ally advantage, forced movement + zone/wall interaction

Existing characters updated for scenarios 20-21:
- Morgana Frostweaver -- Eldritch Blast updated with Repelling Blast invocation: forced_movement_type "push", forced_movement_distance 10. Pushes target 10 ft straight back on every hit. Feature added for Repelling Blast.
- Willow Thornroot -- Thorn Whip added: melee spell attack (30 ft range), 2d6 piercing, pulls target 10 ft toward caster on hit (forced_movement_type "pull", forced_movement_distance 10). Thunderwave also added: CON save DC 15, 2d8 thunder (half on save), push 10 ft on fail.
- Elara Nightwhisper -- Thunderwave added: CON save DC 15, 2d8 thunder (half on save), push 10 ft on fail. Costs 1st-level spell slot.

New monster sheet created:
- Cultist Warlock (monsters/cultist_warlock.json) -- Medium humanoid, CR 2. AC 13, 33 HP. Eldritch Blast with Repelling Blast (1d10+3 force, push 10 ft on hit), Dagger. AI profile: spellcaster. Tests AI-controlled forced movement attacks.

New features implemented to support these scenarios:
- Forced Movement System: Actions can now push, pull, or slide targets on hit (attacks) or on failed save (effects). Three fields on Action: forced_movement_type ("push"/"pull"/"slide"), forced_movement_distance (feet), forced_movement_prone (also knock prone). Push moves target directly away from the source. Pull moves target directly toward the source. Creatures stop if they hit a wall, occupied hex, or the grid edge.
- Shove Tactic: Universal tactic available to every creature (like Dash/Disengage/Dodge). Appears as the 6th entry in the Tactics radial menu. Two choices: "Push 5 ft" (push target 1 hex away) or "Knock Prone" (apply prone condition). Requires a contested Athletics check (attacker Athletics vs defender's higher of Athletics or Acrobatics). Uses the creature's action.
- Shove Choice Popup: When a player clicks Shove in the Tactics menu and selects an adjacent target, a small popup appears with two buttons: "Push 5 ft" and "Knock Prone".
- Visual Effects: Forced movement produces a sliding circle animation from origin to destination (500ms). Color-coded: push = orange, pull = blue, slide = green.
- AI Shove Support: AI scores Shove against adjacent enemies, preferring prone when melee allies are nearby (they benefit from advantage on prone targets). AI also uses actions with forced movement (Repelling Blast, Thunderwave) with a small scoring bonus.
- Builder Support: Actions tab now has a "Forced Movement" section between Teleportation and Summoning: dropdown for type (none/push/pull/slide), number spinner for distance (0-60 ft, step 5), checkbox for "Also Knock Prone".

Scenario 20 -- The Precipice -- is designed to test push and pull mechanics from ranged attacks. Morgana's Repelling Blast pushes enemies on hit (no save), while Willow's Thorn Whip pulls enemies on hit (no save). The narrow grid with walls and edges creates natural boundaries to test push-into-wall stopping and push-to-grid-edge stopping. The orcs are aggressive melee fighters who will rush toward the party, making them ideal push/pull targets. Both characters can also use the universal Shove tactic when enemies get into melee range.

Scenario 20 test steps:
1. Load the encounter and roll initiative. Verify all combatants appear: Morgana and Willow on the west side (left), three orcs on the east side (right). Two wall clusters should be visible at the center of the grid. User notes: Verified.
2. On Morgana's turn, select Eldritch Blast and target the Orc Brute (positioned at [11,3]). If the attack hits, verify the orc is pushed 10 ft (2 hexes) directly AWAY from Morgana. The orc should end up further east. Verify the orange sliding circle visual effect plays from the orc's original position to its new position. Verify the combat log shows a FORCED_MOVEMENT event with "pushed 10 feet". User notes: Verified. Had to reduce the power of Eldritch Blast to 1d2 as the character was one shotting the orcs.
3. Fire Eldritch Blast at the Orc Brute again (or on a later turn). If the orc is now near the east grid edge (column 14-15), verify the push stops at the grid boundary. The orc should NOT be pushed off the map. The combat log should indicate the push distance was reduced (e.g., "pushed 5 feet" instead of 10 if only 1 hex of space remained). User notes: Verified.
4. On Willow's turn, select Thorn Whip and target the Orc Raider (positioned at [11,8]). If the attack hits, verify the orc is pulled 10 ft (2 hexes) directly TOWARD Willow. The orc should end up closer to the west side. Verify a blue sliding circle visual effect plays (pull = blue color). User notes: Verified.
5. Use Thorn Whip on an orc that is already adjacent to Willow (1 hex away). Verify the pull has no movement effect (already adjacent, can't pull closer). The attack damage should still apply normally. User notes: Verified.
6. Position Morgana so that an orc is between her and the central wall cluster. Fire Eldritch Blast at that orc. If it hits, verify the orc is pushed toward the wall and STOPS at the wall hex. The orc should NOT pass through walls. The push distance should be reduced to however many hexes were available before the wall. User notes: Verified.
7. Wait for the orcs to advance into melee range with Morgana or Willow (the Aggressive bonus action should help them close quickly). On a player's turn, open the Tactics menu from the radial menu. Verify "Shove" appears as the 6th option alongside Dash, Disengage, Dodge, Help, and Hide. User notes: Verified. We might want to add a custom icon for shove, as the other five tactics have an icon. Not a priority, just a note.
8. Click "Shove" in the Tactics menu. Verify the UI enters target selection mode. Click an adjacent orc. Verify the ShoveChoicePopup appears with two buttons: "Push 5 ft" and "Knock Prone". User notes: Verified.
9. Click "Push 5 ft" in the ShoveChoicePopup. Verify a contested Athletics check resolves: the combat log should show both the attacker's Athletics roll and the defender's Athletics (or Acrobatics) roll. If the attacker wins, the orc should be pushed 1 hex (5 ft) away. If the attacker loses, the orc stays put. Verify the action is consumed regardless of success/failure. User notes: Verified.
10. On another turn, use Shove again and click "Knock Prone". If the contest succeeds, verify the target orc gains the "prone" condition (visible in the creature info panel). If the contest fails, verify no condition is applied. User notes: Verified.
11. If an orc was knocked prone, verify that melee attacks against the prone orc mention advantage (per 5e rules: attack rolls against prone within 5 ft have advantage). User notes: Verified.
12. Attempt to Shove a non-adjacent orc (more than 1 hex away). Verify the shove is rejected or the target is not valid. Shove requires adjacency (5 ft). User notes: Verified.
13. If Eldritch Blast misses (observe the attack roll), verify that NO push occurs. Forced movement only triggers on a hit, not on a miss. The combat log should show the miss but no FORCED_MOVEMENT event. User notes: Verified.
14. (Edge case) Use Thorn Whip on an orc that has another creature between it and Willow. Verify the pull stops if the path is blocked by the occupied hex (the orc should not pass through another creature). User notes: Verified.
15. (Edge case) Verify that after a successful shove (push 5 ft), the shoving creature does NOT move into the vacated hex automatically. Shove pushes the target but doesn't advance the attacker. User notes: Verified.

Scenario 21 -- Storm Front -- is designed to test AoE forced movement (Thunderwave pushes multiple enemies on failed save), the Shove tactic with a high-STR character (Thorin has 18 STR + Athletics proficiency), and AI-controlled forced movement (the Cultist Warlock uses Repelling Blast). The walls in the center create interesting push trajectories, and the difficult terrain tests movement through rubble after being pushed.

Scenario 21 test steps:
1. Load the encounter and roll initiative. Verify all combatants appear: Elara and Thorin on the west side, Cultist Warlock at [14,6], two hobgoblin soldiers flanking from the east. User notes: Verified.
2. Let the hobgoblins advance toward the party. When at least one hobgoblin is within 15 ft (3 hexes) of Elara, select Thunderwave on Elara's turn. Verify the AoE targeting shows a 15-ft cube originating from Elara. Click to confirm the target area. User notes: Verified after fix.
3. After Thunderwave resolves, check the results for each enemy in the area: enemies who FAILED the CON save (DC 15) should take full 2d8 thunder damage AND be pushed 10 ft away from Elara. Enemies who SUCCEEDED should take half damage and NOT be pushed. Verify the combat log clearly shows which enemies were pushed and which were not. User notes: Verified after fix.
4. If multiple enemies were in the Thunderwave area, verify EACH enemy is pushed independently in their own direction (directly away from Elara). Two enemies on opposite sides of Elara should be pushed in opposite directions. User notes: Verified after fix.
5. Cast Thunderwave when an enemy is between Elara and a wall. If the enemy fails the save, verify the push stops at the wall. The enemy should take full damage regardless of whether the push distance was reduced by the wall. User notes: Verified after fix.
6. Observe the Cultist Warlock's AI behavior. The warlock has Repelling Blast (Eldritch Blast + push 10 ft). When the warlock attacks a player character, verify that on a hit, the target player is pushed 10 ft away from the warlock. Verify the orange visual effect plays for the AI-initiated push. User notes: Verified.
7. Verify the AI warlock's push direction: the player should be pushed directly away from the warlock's position. If the warlock is east of the player, the player should be pushed west. User notes: Verified.
8. On Thorin's turn (18 STR, Athletics proficiency), move him adjacent to a hobgoblin. Open Tactics and select Shove. Click the hobgoblin, then select "Knock Prone" in the popup. Observe the contested check: Thorin should roll d20 + 7 (STR mod +4, proficiency +3) vs the hobgoblin's Athletics or Acrobatics. With Thorin's +7, he should succeed often. Verify the hobgoblin gains the prone condition on success. User notes: Verified.
9. After knocking a hobgoblin prone, attack it with Thorin's Longsword on the same turn (if Extra Attack is available) or the next turn. Verify the attack roll benefits from advantage (attacker within 5 ft of prone target gets advantage per 5e). User notes: Verified.
10. On Thorin's turn, use Shove with "Push 5 ft" against a hobgoblin positioned near a wall. Verify the hobgoblin is pushed 1 hex away from Thorin. If the wall is in the push direction, verify the hobgoblin stops at the wall. User notes: Verified.
11. Try to Shove with Elara (STR 8, no Athletics proficiency). The contest should use d20 + (-1) for Elara. This should fail much more often than Thorin's shoves, demonstrating that STR-based characters are better at shoving. User notes: Verified.
12. Verify that using Shove consumes the character's ACTION for the turn. After shoving, the character should not be able to attack or cast a spell as their action (bonus actions should still be available). User notes: Verified.
13. (Edge case) If the Cultist Warlock misses with Eldritch Blast, verify that no push occurs. Only hits trigger forced movement for attack-based actions. User notes: Verified.
14. (Edge case) Cast Thunderwave when NO enemies are in the area (all enemies out of range). Verify the spell still resolves (spell slot consumed, action used) but no saving throws are rolled and no pushes occur. User notes: Verified.
15. (Edge case) Try to Shove an unconscious enemy (if one is downed). Verify the shove is rejected or has no meaningful effect (unconscious creatures can't resist, but pushing them is mechanically pointless). User notes: Thorin shoves the downed creature 5 ft. I don't mind this being in the tool, I just mostly find it funny.

---

#	Encounter	Grid	Party	Enemies	Primary Tests
22	Fortress of Earth	18x14	Gareth Stoneheart + Ser Marcus	Arcane Sentinel (Mage) + 3 Hobgoblins	Wall of Stone wall creation (concentration-linked), Mold Earth terrain removal (non-concentration), Transmute Rock pit creation, occupied hex skipping for wall/pit, concentration break reverts terrain, AI terrain spells (enemy Mage with Wall of Stone), visual effects, terrain mod in builder tab
23	Thornwall Siege	20x15	Willow + Thorin	Forest Shaman + 2 Wolves + 2 Bandits	Spike Growth zone+terrain combo (difficult terrain + 2d4 zone damage), Entangle terrain+condition (difficult terrain + restrained), AI terrain spells (Forest Shaman with Plant Growth + Entangle), non-concentration terrain persistence (Plant Growth), concentration reversion clears both zone and terrain, stacking terrain from different sources, terrain over water hexes

New characters created for scenarios 22-23:
- Gareth Stoneheart (characters/gareth.json) -- Mountain Dwarf Wizard 9 (School of Transmutation). Wall of Stone (5th level, concentration, terrain_modification="wall", area_sphere radius 10), Spike Growth (2nd level, concentration, terrain_modification="difficult" + zone damage 2d4 piercing), Mold Earth (cantrip, terrain_modification="normal", single hex), Transmute Rock (5th level, concentration, terrain_modification="pit", DEX save DC 17, 4d6 bludgeoning), Fireball, Fire Bolt, Warhammer, Misty Step, Shield. AC 15, 58 HP, INT 20, spell save DC 17. Spell slots: 1(4), 2(3), 3(3), 4(3), 5(1).

Existing characters updated:
- Willow Thornroot -- Added Spike Growth (2nd level, concentration, terrain_modification="difficult" + zone 2d4 piercing, DEX save DC 15) and Entangle (1st level, concentration, terrain_modification="difficult" + STR save DC 15 for restrained).

New monster sheets created:
- Forest Shaman (monsters/forest_shaman.json) -- Medium humanoid, CR 4. AC 13, 45 HP, WIS 16. Entangle (concentration, terrain_modification="difficult", STR save DC 14 for restrained), Plant Growth (non-concentration, terrain_modification="difficult", area_sphere radius 50), Produce Flame (2d8 fire), Quarterstaff. AI profile: spellcaster. Prioritizes terrain control.

Existing monster sheets updated:
- Mage -- Added Wall of Stone (concentration, terrain_modification="wall", area_sphere radius 10, 1/rest). AI-controlled terrain for Scenario 22.

New features implemented to support these scenarios:
- Terrain Modification System: Actions can now dynamically add, remove, or alter terrain hexes during combat. A single field on the Action model (terrain_modification) specifies the TerrainType to apply. Setting "wall" creates impassable walls, "difficult" makes terrain difficult, "normal" clears modifications back to normal ground, "pit" creates hazardous pits.
- Concentration-Linked Reversion: Terrain modifications from concentration spells (Wall of Stone, Spike Growth, Entangle) automatically revert when concentration breaks -- the original terrain is restored. Non-concentration terrain (Mold Earth, Plant Growth) persists permanently.
- Occupied Hex Protection: When creating impassable terrain (wall, pit), hexes occupied by living creatures are skipped. The modification applies to all other valid hexes in the area. This prevents trapping creatures inside walls.
- Zone+Terrain Combos: Spells like Spike Growth create BOTH a persistent damage zone AND difficult terrain simultaneously. Both revert independently when concentration ends.
- Stacking Safety: When terrain modifications revert, only hexes that still match the applied terrain type are restored. If another spell changed the terrain in the meantime, that hex is left as-is.
- Visual Effects: Terrain modifications play an expanding pulse effect centered on the target area. Color-coded by terrain type: stone grey for walls, verdant green for difficult, dark brown for pits, neutral white for normal/clearing.
- AI Scoring: AI considers terrain modification value when scoring actions. Wall/pit creation gets +35 base bonus, difficult terrain +15, terrain removal (normal) +5. Scales with enemy count.
- Builder Tab: Terrain Modification dropdown added to the Actions tab in the creature builder, between Forced Movement and Summoning sections. Options include all 9 terrain types plus "(none)".
- Event System: TERRAIN_MODIFICATION event type added with sound and combat log color mappings.

Scenario 22 -- Fortress of Earth -- is designed to test wall creation, pit creation, terrain removal, and their concentration-linked behavior. Gareth is a high-level wizard with multiple terrain-altering spells (Wall of Stone, Transmute Rock, Mold Earth, Spike Growth), allowing comprehensive testing of the terrain modification system from the player's perspective. The enemy Mage also has Wall of Stone, testing AI-controlled terrain creation. Ser Marcus provides a melee frontliner whose pathing is affected by dynamic terrain changes. The grid has existing cover and difficult terrain to test interaction with dynamic modifications.

Scenario 22 test steps:
1. Load the encounter and roll initiative. Verify all combatants appear: Gareth and Ser Marcus on the west side, Arcane Sentinel (Mage) at [15,6], three Hobgoblin Vanguards on the east side. Verify existing terrain: cover hexes at [8,3] and [8,10], difficult terrain at [5,6]-[5,7] and [12,6]-[12,7]. User notes: Verified.
2. On Gareth's turn, select Wall of Stone from the action menu. Verify AoE targeting mode activates with a hex overlay showing the 10-ft radius (2-hex radius) centered on the hovered hex. Click a hex in the middle of the grid (e.g., [9,6]) to create the wall. User notes: Verified. It really is giant though; less wall like and more mountain like.
3. After casting, verify the terrain modification visual effect plays -- an expanding pulse with stone grey color centered on the target hex. Verify the affected hexes on the grid change to wall terrain (visually distinct). User notes: Verified.
4. Verify the combat log shows a TERRAIN_MODIFICATION event with a message like "Wall of Stone transforms X hexes to wall terrain!" where X is the number of modified hexes. User notes: Verified.
5. Verify that Gareth is now concentrating on Wall of Stone (concentration indicator visible in creature info panel). A 5th-level spell slot should be consumed. User notes: Verified.
6. On Ser Marcus's turn, attempt to move through the newly created wall hexes. Verify that pathfinding routes AROUND the walls -- Marcus cannot walk through them. If Marcus is on one side of the wall and enemies are on the other, the movement path should go around the wall endpoints. User notes: Verified.
7. Let the hobgoblins advance. Observe whether their AI pathfinding correctly routes around the Wall of Stone. The hobgoblins should NOT attempt to walk through the wall hexes. Their paths should adjust to go around the walls. User notes: Verified.
8. Observe the Arcane Sentinel (Mage) AI behavior. The Mage has Wall of Stone (1/rest) and should consider using it if conditions are favorable (2+ enemies in range). If the AI casts Wall of Stone, verify: wall terrain appears at the target location, the visual effect plays, the Mage begins concentrating, and the hexes are properly set to wall terrain. User notes: Could not get the mage to cast this spell. It preferred fireball as its top action, and hold person as the next one.
9. Have an enemy attack Gareth to trigger a concentration save. If Gareth FAILS the CON save, verify that concentration on Wall of Stone ends AND the wall terrain REVERTS to its original state. The hexes that were changed to wall should return to whatever they were before (normal terrain, difficult terrain, etc.). Verify a TERRAIN_MODIFICATION event appears in the log: "Wall of Stone terrain fades away (X hexes restored)." User notes: Verified.
10. If Gareth's concentration holds, test voluntary concentration drop: on Gareth's turn, click "Drop Conc." in the radial menu. Verify the Wall of Stone terrain reverts and the log shows the reversion message. User notes: Verified (tested both).
11. After the wall reverts, on Gareth's next turn, cast Mold Earth targeting one of the existing difficult terrain hexes at [5,6] or [5,7]. Verify: the single hex (radius 0) changes to normal terrain, no concentration is required, and the visual effect plays (neutral white color). User notes: Verified.
12. On a subsequent turn, verify the Mold Earth change persists even though no concentration is active. Move Ser Marcus through the cleared hex -- verify it costs normal movement (5 ft) instead of difficult terrain movement (10 ft). User notes: Verified.
13. Cast Wall of Stone again (if Gareth has another 5th-level slot or for this test, note the resource). Click a target hex where a hobgoblin is standing. Verify the wall terrain is applied to surrounding hexes but the hex occupied by the hobgoblin is SKIPPED -- the hobgoblin should NOT be trapped inside a wall hex. The log should show fewer modified hexes than the full area would suggest. User notes: Verified.
14. On Gareth's turn, cast Transmute Rock targeting a hex cluster near enemies. Verify: pit terrain appears in the 10-ft radius area, enemies in the area make DEX saves (DC 17), damage is applied on failed saves (4d6 bludgeoning, half on success), and occupied hexes are skipped (pit is impassable like wall). Gareth begins concentrating on Transmute Rock. User notes:
15. Verify that casting Transmute Rock while concentrating on Wall of Stone causes Wall of Stone to end first (only one concentration spell at a time). The wall terrain should revert before the pit terrain is applied. User notes: Verified. Weirdly, the terrain that the hobgoblins were standing on were not pits (they did take damage though). I assume this is the same effect where Wall of Stone will build stone around a character; this too will build pits around a character, but still apply damage. I am satisfied with this one, unless you feel the need to push back.
16. Attempt to cast Spike Growth (Gareth also has it). Select the spell, click a target area. Verify BOTH a damage zone (blue/red overlay) AND difficult terrain are created. The zone should deal 2d4 piercing to creatures that fail a DEX save. The terrain should change to difficult. Gareth should begin concentrating. User notes: Verified.
17. Break Gareth's concentration on Spike Growth (attack or voluntary drop). Verify BOTH the zone overlay AND the difficult terrain revert simultaneously. The zone should vanish from the grid, and the hexes should return to their original terrain. User notes: Verified.
18. (Edge case) Cast Wall of Stone at the very edge of the grid (e.g., targeting [1,1] or [17,13]). Verify the modification only applies to valid grid hexes -- out-of-bounds hexes are ignored, and no crash occurs. The count of modified hexes should be less than a full circle. User notes:
19. (Edge case) Cast Mold Earth on a hex that is already normal terrain. Verify the spell still resolves (action consumed) but the hex count should be 0 or the hex is unchanged (no-op for same terrain). No visual effect or event should appear if 0 hexes were actually changed. User notes:
20. (Edge case) If both Gareth and the enemy Mage have wall terrain on the grid at the same time (from separate Wall of Stone casts), break one caster's concentration. Verify that ONLY that caster's wall reverts -- the other caster's walls remain intact. This tests independent modification tracking. User notes: Cannot get the enemy mage to cast this spell.
21. Open the creature builder and navigate to the Actions tab. Create a new test action. Verify the "Terrain Modification" dropdown appears between the Forced Movement section and the Summoning section. Select "wall" from the dropdown, save the action. Verify the terrain_modification field is preserved when loading the creature. User notes: Verified.

Scenario 23 -- Thornwall Siege -- is designed to test the zone+terrain combo (Spike Growth), terrain+condition effects (Entangle), AI-controlled terrain spells, non-concentration terrain persistence, and terrain stacking from multiple casters. The Forest Shaman uses Plant Growth for permanent area denial and Entangle for targeted control, while Willow counters with Spike Growth (zone + terrain combo). The central water hexes test terrain modification over existing non-normal terrain (water -> difficult). Multiple terrain-altering casters on both sides stress-test the stacking and independent reversion systems.

Scenario 23 test steps:
1. Load the encounter and roll initiative. Verify all combatants appear: Willow and Thorin on the west side, Forest Shaman at [16,7], two wolves at [14,5] and [14,9], two bandits at [15,6] and [15,8]. Verify existing terrain: cover hexes at [6,4], [13,4], [6,10], [13,10] and water hexes at [9,7]-[10,8]. User notes: Verified.
2. On Willow's turn, select Spike Growth from the action menu. Click a hex in the path the enemies will use to approach (e.g., [11,7]). Verify TWO things happen simultaneously: (a) a persistent damage zone appears (zone overlay visible on the grid), AND (b) the terrain hexes within the 20-ft radius change to difficult terrain. User notes: Verified. Casters are able to simulataneously concentrate on two spells at once (in this example, used Spike Growth and Moon Beam on accident). Verifed that spells can overlap from previous scenario, and that dropping concentration on one character only removes the terrain this particular character had summoned.
3. Verify Willow begins concentrating on Spike Growth. Verify a 2nd-level spell slot is consumed. Verify the combat log shows a TERRAIN_MODIFICATION event ("Spike Growth transforms X hexes to difficult terrain!"). User notes: Verified.
4. Let the wolves advance toward the party. Observe whether they take zone damage when entering the Spike Growth area (2d4 piercing on entering the zone). Also observe whether the difficult terrain slows their movement through the area (10 ft per hex instead of 5 ft). User notes: Verified.
5. Observe the Forest Shaman AI behavior. The Shaman has Plant Growth (non-concentration, ai_priority 7) and Entangle (concentration, ai_priority 8). If the AI casts Plant Growth, verify: difficult terrain appears in a large 50-ft radius area, no concentration is started, and no zone overlay appears (Plant Growth is terrain-only, not a zone). User notes: Verified.
6. If the Forest Shaman used Plant Growth, verify that the difficult terrain persists indefinitely. Even if the Shaman is later killed or incapacitated, the Plant Growth terrain should NOT revert (it has no concentration link). User notes: Verified.
7. If the Forest Shaman casts Entangle instead, verify: difficult terrain appears in a 20-ft radius, enemies in the area make STR saves (DC 14), and those who fail gain the "restrained" condition. The Shaman should begin concentrating on Entangle. User notes: Verified.
8. Test terrain stacking from different sources: If both Willow's Spike Growth and the Shaman's Plant Growth/Entangle overlap on some hexes, observe how the terrain is tracked. When one caster's concentration breaks, only THEIR terrain modifications should revert. The other caster's terrain should remain. User notes: Verified, noted above.
9. For stacking safety: If Willow's Spike Growth created difficult terrain on a hex, and then the Shaman's Plant Growth also targets that same hex (already difficult), verify the hex is skipped as a no-op (already matches the target terrain). The Shaman's modification record should NOT include this hex, so reverting the Shaman's spell doesn't accidentally clear Willow's difficult terrain. User notes: Verified.
10. Cast Entangle with Willow (costs 1st-level slot, requires concentration). This should drop concentration on Spike Growth first. Verify that BOTH the Spike Growth zone AND its difficult terrain revert before Entangle is applied. Verify Entangle then creates new difficult terrain and applies restrained to enemies who fail the STR save. User notes: As noted above, concentraion system can allow concentration on two different spells, or somehow not dropping concentration allows the terrain to persist until concentration is actually dropped. Not sure which.
11. On Thorin's turn, move him through a difficult terrain hex (from Spike Growth, Plant Growth, or Entangle). Verify movement costs 10 ft per hex instead of the normal 5 ft. Thorin's speed is 25 ft, so he should be able to move fewer hexes when traversing difficult terrain. User notes: Verified.
12. Test terrain modification over water hexes: Cast Spike Growth or Entangle so the 20-ft radius overlaps the central water hexes [9,7]-[10,8]. Water is already difficult terrain. Verify the water hexes are skipped as no-ops (already difficult) or the terrain changes to "difficult" type. On reversion, verify the water hexes return to water (if they were modified) rather than becoming normal terrain. User notes: Verified.
13. Kill the Forest Shaman while it is concentrating on Entangle. Verify the Entangle terrain reverts (concentration ends when the caster dies/is downed). If Plant Growth was also used by the Shaman (non-concentration), verify Plant Growth terrain remains even after the Shaman dies. User notes: Verified.
14. After all terrain modifications are resolved, verify the original terrain (water, cover) at the pre-set positions is intact and unmodified (or properly restored if it was affected by terrain spells). User notes: Verified.
15. (Edge case) Cast Spike Growth over the cover hexes at [6,4] or [13,4]. Verify cover_half terrain is overwritten by difficult terrain during the spell. When concentration ends, verify the cover_half terrain is restored (original terrain recorded and reverted). User notes: Verified.
16. (Edge case) Cast Entangle on an area with no enemies present. Verify: the difficult terrain is applied (terrain modification works regardless of creature presence), no saving throws are rolled (no targets), and Willow begins concentrating. The terrain change should still happen even with no creatures to restrain. User notes: Verified.
17. (Edge case) Have both Willow and the Forest Shaman lose concentration on their respective terrain spells in the same round (e.g., both take damage and fail CON saves). Verify both sets of terrain revert independently without interfering with each other. User notes: Verified.
18. (Edge case) Verify the visual effect for difficult terrain creation uses a green-tinted expanding pulse (different color from the grey wall effect in Scenario 22). User notes: Verified.

Bugs found and fixed during scenarios 22-23 playtesting:
- Dual concentration bug: casting a new concentration spell (e.g., Moonbeam) after a terrain-modifying concentration spell (e.g., Spike Growth) did NOT revert the first spell's terrain. Root cause: cleanup_terrain_modifications() only checked whether the caster was concentrating (on anything), not on WHICH spell. Fixed by comparing the CONCENTRATING condition's extra_data["spell"] field against the terrain mod's spell_name. If they don't match, the terrain reverts. (Fixed -- src/combat/terrain_effects.py)
- AI Mage could not cast Wall of Stone: terrain-only actions (no saving throw, no attack) were invisible to the AI scoring pipeline. The "effect actions" category required a saving_throw with damage_on_fail or conditions_on_fail, which Wall of Stone doesn't have. Fixed by adding a new "terrain" scoring category in generate_scored_actions() for actions with terrain_modification but no saving throw. Also updated the AI executor to use execute_effect_at_hex() when target_hex is set (so terrain is placed near enemies, not at the caster). (Fixed -- src/ai/scoring.py, src/ai/controller.py, src/ai/executor.py)
- Wall of Stone area feels like a "mountain" rather than a wall (Scenario 22 step 2): area_size=10 creates a 2-hex radius filled circle (~7 hexes), which is more of a mass than a thin wall. In 5e, Wall of Stone creates shaped panels. This is a design limitation of the current area_sphere targeting system -- true panel-shaped walls would require a different targeting mode. Noted for future improvement.