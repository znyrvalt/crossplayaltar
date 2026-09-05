# P4 — Paladin shrapnel via clay_ball CMD 8

Original S1 paladin classes spawn clay_ball CMD 8 display items
(`massive_axe` shrapnel visual) on hits. Current 2.0.5 paladin uses
golden_sword/shield block-style displays instead (verified in
`fabric/weapon` + `command/CommandRegistrar` display call sites).

State of the deliverable:
- `altarsmp:clay_ball_c8` exists (the pack declares CMD 8 and CrazySlots-era
  content still references it) with the massive_axe model converted;
- the CURRENT golden_sword/shield displays are mapped in
  `altarsmp-displays.yml` as vanilla pass-through entries, so Bedrock matches
  current Java exactly.

If P4 is applied (re-adding clay 8 spawns), Bedrock needs no changes: the
display item is already translated to `altarsmp:clay_ball_c8` and its
attachable renders the shrapnel model.
