# P0 — custom model data on copper diamond armour (worn visuals on Bedrock)

Problem: the CopperDiamond* pieces (armor.json entries with
`base_material: DIAMOND_*`, `equippable_model: custom:copper`, no CMD) give
Geyser no hook — Bedrock wears vanilla diamond armour, Java wears the copper
equippable layer.

Fix (Java-neutral): where content armor entries carry an equippable model but
`custom_model_data == null`, stamp CMD 1 at build time:

    ItemMeta meta = stack.getItemMeta();
    if ((meta.getCustomModelData() == null || meta.getCustomModelData() == 0)
            && behavior.equippableModel() != null) {
        meta.setCustomModelData(1);          // bedrock mapping hook
        stack.setItemMeta(meta);
    }

Java visual impact: none — vanilla `items/diamond_helmet.json` … have no
threshold-1 branch, so held look is unchanged; the equippable layer already
uses `custom:copper`.

After applying this patch, re-run the generator (`tools/` +
`docs/catalog` rebuild — it is catalog-driven, so the four
`minecraft:diamond_helmet|1` … `minecraft:diamond_boots|1` definitions with
copper armor-layer attachables appear automatically; no hand-editing).
Without the patch, Bedrock keeps vanilla diamond worn-look and everything
else in this package is unaffected.
