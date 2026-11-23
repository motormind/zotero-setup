#!/usr/bin/env bash
# curl examples for the Zotero Web API v3. Expects ZOTERO_API_KEY and GROUP in the environment:
#   set -a; source .env; set +a; GROUP=<group-id> bash examples/curl/zotero.sh
set -euo pipefail
: "${ZOTERO_API_KEY:?set ZOTERO_API_KEY}" "${GROUP:?set GROUP to your group id}"

API=https://api.zotero.org
H=(-H "Zotero-API-Version: 3" -H "Zotero-API-Key: ${ZOTERO_API_KEY}")

echo "# key permissions"
curl -s "${H[@]}" "$API/keys/$ZOTERO_API_KEY" | python3 -m json.tool

echo "# 5 most recently added papers"
curl -s "${H[@]}" "$API/groups/$GROUP/items/top?sort=dateAdded&direction=desc&limit=5" \
  | python3 -c 'import json,sys; [print(i["key"], i["data"].get("title")) for i in json.load(sys.stdin)]'

echo "# search (incl. full text)"
curl -s "${H[@]}" "$API/groups/$GROUP/items/top?q=transformer&qmode=everything&format=keys"

echo "# formatted bibliography (APA)"
curl -s "${H[@]}" "$API/groups/$GROUP/items/top?limit=5&format=bib&style=apa"

echo "# headers: Total-Results, Link (pagination), Last-Modified-Version"
curl -s -D - -o /dev/null "${H[@]}" "$API/groups/$GROUP/items/top?limit=1" \
  | grep -iE '^(total-results|link|last-modified-version):'
