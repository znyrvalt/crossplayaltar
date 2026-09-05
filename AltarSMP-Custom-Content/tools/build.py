#!/usr/bin/env python3
"""Generate the AltarSMP Bedrock crossplay package (mappings + resource pack + GDE template)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from altarbedrock import build as BUILD  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rp", required=True, help="extracted AltarSMP Java resource pack")
    ap.add_argument("--fab", required=True, help="extracted altarsmp-fabric-2.0.5.jar")
    ap.add_argument("--fabsrc", required=True, help="fabric 2.0.5 sources dir")
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--out", required=True, help="AltarSMP-Custom-Content deliverable dir")
    ap.add_argument("--gde-repo", default=None)
    ap.add_argument("--version", default="2.0.5")
    a = ap.parse_args()
    b, report = BUILD.run(a.rp, a.fab, a.fabsrc, a.out, a.catalog,
                          gde_repo=a.gde_repo, version=a.version)
    print(json.dumps(report["stats"], indent=1))
    print("warnings:", len(b.warnings))
    for w in b.warnings[:40]:
        print("  -", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
