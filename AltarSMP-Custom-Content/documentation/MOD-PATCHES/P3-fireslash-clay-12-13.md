# P3 — FireSlash fire displays (clay_ball CMD 12/13)

Verified from `x_origsrc/com/altarsmp/weapons/FireSlashWeapon.java`:

    private ItemDisplay spawnOldFireDisplay(...) {
        ItemStack = CLAY_BALL + setCustomModelData(12)   // and 13 elsewhere
        transform = FIXED
        new Transformation(translate(-0.75,-0.75,-0.1), rot, scale(1.5,1.5,0.2), rot)
        brightness(15,15)
    }

Facts for the parity record:
- 2.0.5 does not spawn these at all (current fire-wave is pure particles +
  sounds, both vanilla and auto-mapped by Geyser — Bedrock already matches
  the CURRENT behaviour 1:1).
- Even in the original, the modern pack dropped clay_ball dispatch entries
  12/13, so CMD 12/13 renders the vanilla clay ball on 1.21+ Java.
- GeyserDisplayEntity does NOT sync the server-set display transformation
  (the 1.5x/0.2 flatten + translation + full-brightness trick), so restored
  spawns would look squashed-vs-unsquashed across editions.

If restoring the old fire visual: re-add the spawns, add threshold 12/13 →
a fire model to `assets/minecraft/items/clay_ball.json` (no such model ships
in the pack today — one must be authored), then re-run `tools/` — the
catalog-driven generator maps + converts automatically. Until then, note in
DIFFERENCES §3.2/§4.1 stands: intentionally unconverted.
