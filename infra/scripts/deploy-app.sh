#!/usr/bin/env bash
set -euo pipefail

: "${NAMESPACE:?Set NAMESPACE}"
: "${IMAGE:?Set IMAGE to the published image digest}"
[[ "$IMAGE" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || {
  echo 'Deploy an immutable GHCR image digest.' >&2
  exit 1
}

# Firewall updates can take a little time to propagate.
for attempt in {1..12}; do
  if kubectl -n "$NAMESPACE" get deployment aimo --request-timeout=10s >/dev/null; then
    break
  fi
  if [[ "$attempt" == 12 ]]; then
    echo 'Cluster/deployment unavailable. Complete the one-time Terraform setup first.' >&2
    exit 1
  fi
  sleep 5
done
replicas=$(kubectl -n "$NAMESPACE" get deployment aimo -o jsonpath='{.spec.replicas}')
if [[ "$replicas" != 1 ]]; then
  echo 'Finish database bootstrap/import and set app_replicas=1 before enabling deployment.' >&2
  exit 1
fi

previous_image=$(kubectl -n "$NAMESPACE" get deployment aimo -o 'jsonpath={.spec.template.spec.containers[?(@.name=="aimo")].image}')
test -n "$previous_image"
if [[ "$previous_image" != "$IMAGE" ]]; then
  kubectl -n "$NAMESPACE" set image deployment/aimo "aimo=$IMAGE"
elif [[ "${LLM_REFRESHED:-false}" == true ]]; then
  # Secret-backed environment variables are read only when a Pod starts.
  kubectl -n "$NAMESPACE" rollout restart deployment/aimo
fi
if ! kubectl -n "$NAMESPACE" rollout status deployment/aimo --timeout=5m; then
  if [[ "$previous_image" != "$IMAGE" ]]; then
    echo 'New image did not become ready; restoring the previous image.' >&2
    kubectl -n "$NAMESPACE" set image deployment/aimo "aimo=$previous_image"
    kubectl -n "$NAMESPACE" rollout status deployment/aimo --timeout=5m
  fi
  exit 1
fi
printf 'Deployed %s\n' "$IMAGE"
