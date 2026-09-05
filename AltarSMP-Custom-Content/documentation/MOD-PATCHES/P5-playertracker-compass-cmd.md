# P5 — PlayerTrackerItem compass branch (optional visual)

`recovery_compass` CMD 2000 (PlayerTrackerItem.java, tracked-player marker)
has NO item-model entry in the resource pack: both Java and Bedrock show the
vanilla recovery compass — the 2000 sentinel never had a model, it is a
server-side data carrier. Listed for completeness so parity reviewers do not
misread its absence from the mapping as a packer omission.

To give it a Bedrock-side visual: add threshold 2000 to
`assets/minecraft/items/recovery_compass.json` + author the model in the pack,
then re-run `tools/` (catalog-driven; the variant maps itself).
