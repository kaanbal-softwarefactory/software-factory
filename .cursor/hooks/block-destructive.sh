#!/usr/bin/env bash
# Bloquea comandos destructivos salvo aprobación explícita en el prompt.
set -euo pipefail
input=$(cat)
command=$(echo "$input" | python -c "import sys,json; print(json.load(sys.stdin).get('command',''))" 2>/dev/null || echo "")

if echo "$command" | grep -qE 'kubectl delete|git push --force|rm -rf /|mkfs|dd if='; then
  echo '{"permission":"deny","userMessage":"Comando destructivo bloqueado. Pide aprobación explícita al usuario."}'
  exit 0
fi

echo '{"permission":"allow"}'
