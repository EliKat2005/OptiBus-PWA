#!/bin/bash
# =============================================
# OptiBus — Copyright Header Injector
# =============================================
# Añade cabeceras legales automáticamente a archivos .py y .js
# Uso: ./scripts/add_headers.sh
# =============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

HEADER_PY="# Copyright (c) 2026 OptiBus. All rights reserved. Proprietary Software."

HEADER_JS="// Copyright (c) 2026 OptiBus. All rights reserved. Proprietary Software."

# ── Python files ──
echo "Adding headers to Python files..."
find "$ROOT_DIR/backend" -name "*.py" -not -path "*/tests/*" | while read -r file; do
    if ! head -n 1 "$file" | grep -q "Copyright (c) 2026 OptiBus"; then
        echo "[PY]  $file"
        # Detect shebang lines
        if head -n 1 "$file" | grep -q "^#!"; then
            # Insert after shebang
            awk 'NR==1{print; print "'"$HEADER_PY"'"; next}1' "$file" > "${file}.tmp"
        else
            echo "$HEADER_PY" > "${file}.tmp"
            cat "$file" >> "${file}.tmp"
        fi
        mv "${file}.tmp" "$file"
    fi
done

# ── JavaScript files ──
echo "Adding headers to JavaScript files..."
find "$ROOT_DIR/frontend" -name "*.js" | while read -r file; do
    if ! head -n 1 "$file" | grep -q "Copyright (c) 2026 OptiBus"; then
        echo "[JS]  $file"
        echo "$HEADER_JS" > "${file}.tmp"
        cat "$file" >> "${file}.tmp"
        mv "${file}.tmp" "$file"
    fi
done

echo "✅ Copyright headers added."