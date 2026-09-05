# P2 — nuke alarm / bloodlust sounds: play registered event ids

Current code plays raw ids `custom/nuke_incoming`, `custom/nuke_explosion`
(NukeZoneManager.java:414, EclipseSwordWeapon.java:303, StrikerWeapon.java:139)
which do not match the resource-pack event names `minecraft:custom.nuke_incoming`
→ silent on Java too. BloodlustWeapon.java:491 plays `custom:bloodlust.resurface`
/ `.dive` which no reference file registers at all.

Fix:

    Fx.sound(level, pos, "minecraft:custom.nuke_incoming", vol, pitch);
    Fx.sound(level, pos, "minecraft:custom.nuke_explosion", vol, pitch);

and either ship oggs for the two bloodlust events or drop the calls.

The generated pack already defines bedrock keys `custom.nuke_incoming`,
`custom.nuke_explosion` (+ `minecraft.*` aliases, whichever form Geyser's
sound translator forwards), so after this patch both sides audibly match.
Until the patch, the nuke alarm is silent on BOTH sides exactly like today's
Java server — no Bedrock regression, but a faithful conversion of a latent
bug worth knowing about.
