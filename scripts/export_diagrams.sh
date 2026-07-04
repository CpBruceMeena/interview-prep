#!/usr/bin/env bash
# ===========================================================================
# export_diagrams.sh
# Export draw.io .drawio files to SVG/PNG for embedding in MkDocs site.
# Usage:
#   ./scripts/export_diagrams.sh <input.drawio> [format]
#
# Examples:
#   ./scripts/export_diagrams.sh low-level-design/parking-lot/parking-lot-hld.drawio
#   ./scripts/export_diagrams.sh low-level-design/parking-lot/parking-lot-hld.drawio png
#
# The output is saved alongside the input file, e.g.
#   low-level-design/parking-lot/parking-lot-hld.svg
# ===========================================================================

set -euo pipefail

DRAWIO_BIN="/Applications/draw.io.app/Contents/MacOS/draw.io"

if [ ! -f "$DRAWIO_BIN" ]; then
    echo "❌ draw.io Desktop not found at $DRAWIO_BIN"
    echo "   Install from https://github.com/jgraph/drawio-desktop/releases"
    exit 1
fi

INPUT="${1:?Usage: $0 <input.drawio> [format]}"
FORMAT="${2:-svg}"

if [ ! -f "$INPUT" ]; then
    echo "❌ Input file not found: $INPUT"
    exit 1
fi

OUTPUT="${INPUT%.drawio}.$FORMAT"

echo "🔧 Exporting $INPUT → $OUTPUT ($FORMAT)"
"$DRAWIO_BIN" --export --format "$FORMAT" --output "$OUTPUT" "$INPUT"

if [ -f "$OUTPUT" ]; then
    SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo "✅ Exported successfully: $OUTPUT ($SIZE)"
else
    echo "❌ Export failed"
    exit 1
fi
