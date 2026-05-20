#!/bin/bash
# Upload all files from a folder to the Document Search API.
# Duplicates are automatically rejected by the API (SHA-256 dedup).
# Usage: ./scripts/upload_folder.sh /path/to/folder

FOLDER="${1:-$HOME/Downloads/House/00_to_be_sorted}"
API="https://api.localhost/ingest/upload"

if [ ! -d "$FOLDER" ]; then
    echo "Error: $FOLDER is not a directory"
    exit 1
fi

echo "Uploading files from: $FOLDER"
echo "---"

success=0
skipped=0
failed=0

for file in "$FOLDER"/*; do
    [ -f "$file" ] || continue
    name=$(basename "$file")

    resp=$(curl -sk -X POST "$API" -F "file=@$file" -w "\n%{http_code}" 2>/dev/null)
    code=$(echo "$resp" | tail -1)
    body=$(echo "$resp" | sed '$d')

    if [ "$code" = "200" ]; then
        category=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category',''))" 2>/dev/null)
        echo "✓ $name → $category"
        ((success++))
    elif echo "$body" | grep -qi "duplicate"; then
        echo "⊘ $name (duplicate, skipped)"
        ((skipped++))
    else
        echo "✗ $name (HTTP $code)"
        ((failed++))
    fi
done

echo "---"
echo "Done: $success uploaded, $skipped duplicates skipped, $failed failed"
