#!/usr/bin/env bash
# End-to-end smoke test against a running instance.
# Proves multi-module integration: auth -> conversation -> customer data ->
# knowledge base -> AI -> validation -> escalation -> agent dashboard -> feedback.
set -euo pipefail

BASE="${BASE_URL:-http://127.0.0.1:8000}"
PASSWORD="${SEED_PASSWORD:-DemoPassw0rd!}"

json() { python3 -c "import sys, json; print(json.load(sys.stdin)$1)"; }
step() { printf '\n== %s\n' "$1"; }

step "Health"
curl -sf "$BASE/api/v1/health" | json "['status']"

step "Customer signs in"
CUSTOMER_TOKEN=$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"customer@example.com\",\"password\":\"$PASSWORD\"}" | json "['accessToken']")

step "Conversation is created"
CONVERSATION_ID=$(curl -sf -X POST "$BASE/api/v1/conversations" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" | json "['conversationId']")
echo "conversation $CONVERSATION_ID"

step "Assistant answers a supported question"
ANSWER=$(curl -sf -X POST "$BASE/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Why was I charged twice for my order?"}')
echo "$ANSWER" | json "['status']" | grep -qx ANSWERED
MESSAGE_ID=$(echo "$ANSWER" | json "['messageId']")

step "Feedback is recorded"
curl -sf -X POST "$BASE/api/v1/conversations/$CONVERSATION_ID/feedback" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"messageId\":\"$MESSAGE_ID\",\"rating\":\"HELPFUL\"}" | json "['rating']"

step "A request for a person escalates deterministically"
ESCALATED=$(curl -sf -X POST "$BASE/api/v1/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Please let me speak to a human agent"}')
echo "$ESCALATED" | json "['escalationReason']" | grep -qx CUSTOMER_REQUEST

step "Another customer is refused access (403)"
OTHER_TOKEN=$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"customer2@example.com\",\"password\":\"$PASSWORD\"}" | json "['accessToken']")
STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $OTHER_TOKEN" "$BASE/api/v1/conversations/$CONVERSATION_ID")
[ "$STATUS" = "403" ] || { echo "expected 403, got $STATUS"; exit 1; }
echo "403 as expected"

step "Agent sees the escalated case with context"
AGENT_TOKEN=$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"agent@example.com\",\"password\":\"$PASSWORD\"}" | json "['accessToken']")
CASE_ID=$(curl -sf -H "Authorization: Bearer $AGENT_TOKEN" "$BASE/api/v1/agent/cases" | json "[0]['caseId']")
curl -sf -H "Authorization: Bearer $AGENT_TOKEN" "$BASE/api/v1/agent/cases/$CASE_ID" | json "['reason']"

step "A customer cannot read an agent case (403)"
STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $CUSTOMER_TOKEN" "$BASE/api/v1/agent/cases/$CASE_ID")
[ "$STATUS" = "403" ] || { echo "expected 403, got $STATUS"; exit 1; }
echo "403 as expected"

step "Agent resolves the case"
curl -sf -X PATCH "$BASE/api/v1/agent/cases/$CASE_ID" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"status":"RESOLVED"}' | json "['status']"

printf '\nSmoke test passed.\n'
