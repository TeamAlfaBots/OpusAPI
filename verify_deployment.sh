#!/usr/bin/env bash
# Post-deployment verification — run: ./verify_deployment.sh https://your-app.onrender.com YOUR_API_KEY
set -euo pipefail

BASE="${1:?Usage: $0 <base_url> <api_key>}"
KEY="${2:?Usage: $0 <base_url> <api_key>}"
VID="dQw4w9WgXcQ"
pass=0; fail=0
ok()   { echo "  ✅ $1"; pass=$((pass+1)); }
bad()  { echo "  ❌ $1"; fail=$((fail+1)); }

echo "== 1. /health =="
[[ "$(curl -s "$BASE/health" | grep -c '"online"')" == 1 ]] && ok "health online" || bad "health"

echo "== 2. /download without API key -> 401 =="
[[ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/download?url=$VID&type=audio")" == 401 ]] && ok "unauthorized blocked" || bad "auth gate"

echo "== 3. /download with key -> token =="
RESP=$(curl -s -H "X-API-Key: $KEY" "$BASE/download?url=$VID&type=audio")
TOKEN=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('download_token',''))")
[[ -n "$TOKEN" ]] && ok "token issued (${TOKEN:0:10}…)" || { bad "no token: $RESP"; exit 1; }

echo "== 4. /stream with token -> audio bytes =="
CODE=$(curl -s -H "X-Download-Token: $TOKEN" -H "Range: bytes=0-262143" -o /tmp/verify.m4a -w '%{http_code}' "$BASE/stream/$VID?type=audio")
SIZE=$(stat -c%s /tmp/verify.m4a 2>/dev/null || stat -f%z /tmp/verify.m4a)
[[ "$CODE" == 206 || "$CODE" == 200 ]] && [[ "$SIZE" -gt 100000 ]] && ok "streamed $SIZE bytes (HTTP $CODE)" || bad "stream HTTP $CODE, $SIZE bytes"

echo "== 5. reuse token -> rejected =="
[[ "$(curl -s -o /dev/null -w '%{http_code}' -H "X-Download-Token: $TOKEN" "$BASE/stream/$VID?type=audio")" == 403 ]] && ok "one-time enforcement" || bad "token reuse allowed!"

echo "== 6. garbage token -> rejected =="
[[ "$(curl -s -o /dev/null -w '%{http_code}' -H "X-Download-Token: fake" "$BASE/stream/$VID?type=audio")" == 403 ]] && ok "invalid token blocked" || bad "invalid token accepted!"

echo
echo "RESULT: $pass passed, $fail failed"
[[ $fail == 0 ]] && echo "🎉 Deployment verified — plug $BASE into your Telegram bot."
