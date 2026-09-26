#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Kaanbal Engine — Cluster Health Check
# ══════════════════════════════════════════════════════════════
# Quick verification of all deployed apps, ArgoCD, and services.
# Run on the cluster master node or SCP + SSH:
#   scp -i factory.pem scripts/cluster-health.sh ubuntu@<IP>:/tmp/
#   ssh -i factory.pem ubuntu@<IP> "bash /tmp/cluster-health.sh"
# ══════════════════════════════════════════════════════════════

set -euo pipefail

PASS=0
FAIL=0
WARN=0

check() {
  local name="$1"
  local result="$2"
  if [ "$result" = "ok" ]; then
    echo "  ✓ $name"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $name — $result"
    FAIL=$((FAIL + 1))
  fi
}

warn() {
  local name="$1"
  local msg="$2"
  echo "  ⚠ $name — $msg"
  WARN=$((WARN + 1))
}

echo "═══════════════════════════════════════════════════════════"
echo " Kaanbal Engine — Cluster Health Check"
echo " $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════════════════════"

# ── 1. Nodes ──────────────────────────────────────────────────
echo ""
echo "── Nodes ──"
NODE_COUNT=$(sudo kubectl get nodes --no-headers 2>/dev/null | wc -l)
NOT_READY=$(sudo kubectl get nodes --no-headers 2>/dev/null | grep -v " Ready " | wc -l)
check "Cluster has nodes ($NODE_COUNT)" "$([ "$NODE_COUNT" -gt 0 ] && echo ok || echo 'no nodes')"
check "All nodes Ready" "$([ "$NOT_READY" -eq 0 ] && echo ok || echo "$NOT_READY not ready")"

# ── 2. ArgoCD ─────────────────────────────────────────────────
echo ""
echo "── ArgoCD ──"
ARGOCD_PODS=$(sudo kubectl get pods -n argocd --no-headers 2>/dev/null | grep -c "Running" || true)
check "ArgoCD pods running" "$([ "$ARGOCD_PODS" -gt 0 ] && echo ok || echo 'no running pods')"

ARGOCD_APPS=$(sudo kubectl get applications -n argocd --no-headers 2>/dev/null)
TOTAL_APPS=$(echo "$ARGOCD_APPS" | wc -l)
SYNCED=$(echo "$ARGOCD_APPS" | grep -c "Synced" || true)
HEALTHY=$(echo "$ARGOCD_APPS" | grep -c "Healthy" || true)
check "ArgoCD apps exist ($TOTAL_APPS)" "$([ "$TOTAL_APPS" -gt 0 ] && echo ok || echo 'no apps')"
check "All apps Synced ($SYNCED/$TOTAL_APPS)" "$([ "$SYNCED" -eq "$TOTAL_APPS" ] && echo ok || echo "$((TOTAL_APPS - SYNCED)) not synced")"
check "All apps Healthy ($HEALTHY/$TOTAL_APPS)" "$([ "$HEALTHY" -eq "$TOTAL_APPS" ] && echo ok || echo "$((TOTAL_APPS - HEALTHY)) not healthy")"

echo ""
echo "  App Details:"
echo "$ARGOCD_APPS" | while read -r line; do
  APP_NAME=$(echo "$line" | awk '{print $1}')
  SYNC=$(echo "$line" | awk '{print $2}')
  HEALTH=$(echo "$line" | awk '{print $3}')
  ICON="✓"
  [ "$SYNC" != "Synced" ] && ICON="✗"
  [ "$HEALTH" != "Healthy" ] && ICON="✗"
  printf "    %s %-30s %s %s\n" "$ICON" "$APP_NAME" "$SYNC" "$HEALTH"
done

# ── 3. Kaanbal API ──────────────────────────────────────────────
echo ""
echo "── Kaanbal API ──"
API_POD_IP=$(sudo kubectl get pods -n prod -l app=kaanbal-api -o jsonpath='{.items[0].status.podIP}' 2>/dev/null || true)
if [ -n "$API_POD_IP" ]; then
  API_HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "http://$API_POD_IP:8000/health" --max-time 5 2>/dev/null || echo "000")
  check "kaanbal-api health ($API_POD_IP)" "$([ "$API_HEALTH" = "200" ] && echo ok || echo "HTTP $API_HEALTH")"
  API_READY=$(curl -s -o /dev/null -w '%{http_code}' "http://$API_POD_IP:8000/ready" --max-time 5 2>/dev/null || echo "000")
  check "kaanbal-api ready" "$([ "$API_READY" = "200" ] && echo ok || echo "HTTP $API_READY")"
  API_IMAGE=$(sudo kubectl get pods -n prod -l app=kaanbal-api -o jsonpath='{.items[0].spec.containers[0].image}' 2>/dev/null)
  echo "  ℹ Image: $API_IMAGE"
else
  check "kaanbal-api pod exists" "no pod found"
fi

# ── 4. Per-App Health ─────────────────────────────────────────
echo ""
echo "── App Pods ──"
for NS in dev staging prod; do
  PODS=$(sudo kubectl get pods -n $NS --no-headers 2>/dev/null | grep -v "Completed" || true)
  if [ -n "$PODS" ]; then
    echo "  [$NS]"
    echo "$PODS" | while read -r line; do
      POD_NAME=$(echo "$line" | awk '{print $1}')
      READY=$(echo "$line" | awk '{print $2}')
      STATUS=$(echo "$line" | awk '{print $3}')
      ICON="✓"
      [ "$STATUS" != "Running" ] && ICON="✗"
      # Check if not fully ready (e.g., 0/1)
      READY_COUNT=$(echo "$READY" | cut -d/ -f1)
      TOTAL_COUNT=$(echo "$READY" | cut -d/ -f2)
      [ "$READY_COUNT" != "$TOTAL_COUNT" ] && ICON="⚠"
      printf "    %s %-40s %s %s\n" "$ICON" "$POD_NAME" "$READY" "$STATUS"
    done
  fi
done

# ── 5. EMQX-specific health ──────────────────────────────────
echo ""
echo "── EMQX Health ──"
for NS in dev staging prod; do
  EMQX_IP=$(sudo kubectl get pods -n $NS -l app=emqx-001 -o jsonpath='{.items[0].status.podIP}' 2>/dev/null || true)
  if [ -n "$EMQX_IP" ] && [ "$EMQX_IP" != "" ]; then
    EMQX_STATUS=$(curl -s "http://$EMQX_IP:18083/api/v5/status" --max-time 5 2>/dev/null || echo "unreachable")
    EMQX_OK=$(echo "$EMQX_STATUS" | grep -c "running" || true)
    check "emqx-001 $NS ($EMQX_IP)" "$([ "$EMQX_OK" -gt 0 ] && echo ok || echo "$EMQX_STATUS")"
  fi
done

# ── 6. n8n-specific health ───────────────────────────────────
echo ""
echo "── n8n Health ──"
for NS in dev staging prod; do
  N8N_IP=$(sudo kubectl get pods -n $NS -l app=n8n-factory-001 -o jsonpath='{.items[0].status.podIP}' 2>/dev/null || true)
  if [ -n "$N8N_IP" ] && [ "$N8N_IP" != "" ]; then
    N8N_HEALTH=$(curl -s -o /dev/null -w '%{http_code}' "http://$N8N_IP:5678/healthz" --max-time 5 2>/dev/null || echo "000")
    check "n8n-factory-001 $NS ($N8N_IP)" "$([ "$N8N_HEALTH" = "200" ] && echo ok || echo "HTTP $N8N_HEALTH")"
  fi
done

# ── 7. Tailscale ──────────────────────────────────────────────
echo ""
echo "── Tailscale ──"
TS_PODS=$(sudo kubectl get pods -n tailscale --no-headers 2>/dev/null | grep -c "Running" || true)
check "Tailscale operator running" "$([ "$TS_PODS" -gt 0 ] && echo ok || echo 'no pods')"
TS_SVCS=$(sudo kubectl get svc -n tailscale --no-headers 2>/dev/null | wc -l || true)
echo "  ℹ Tailscale services: $TS_SVCS"

# ── 8. Vault ──────────────────────────────────────────────────
echo ""
echo "── Vault ──"
VAULT_PODS=$(sudo kubectl get pods -n vault --no-headers 2>/dev/null | grep -c "Running" || true)
check "Vault pod running" "$([ "$VAULT_PODS" -gt 0 ] && echo ok || echo 'no pods')"

# ── 9. MongoDB ────────────────────────────────────────────────
echo ""
echo "── MongoDB ──"
MONGO_PODS=$(sudo kubectl get pods -n prod -l app=datastore --no-headers 2>/dev/null | grep -c "Running" || true)
check "MongoDB pod running" "$([ "$MONGO_PODS" -gt 0 ] && echo ok || echo 'no pods')"

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo " Results: $PASS passed, $FAIL failed, $WARN warnings"
echo "═══════════════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
