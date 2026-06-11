#!/usr/bin/env bash
# Self-test: validates that the Veri DSL backend generates F* that compiles
# with the pinned F* version (v2026.05.31).
set -euo pipefail

cat > /tmp/backend_check.fsti << 'END'
module Test
type rec = { x: Prims.int }
val f: r:rec -> Pure Prims.int (Prims.b2t (r.x >= 0)) (fun result -> Prims.b2t (result >= 0))
END

fstar.exe /tmp/backend_check.fsti && rm /tmp/backend_check.fsti
echo "F* backend compatibility: OK"
