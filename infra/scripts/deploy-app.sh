#!/usr/bin/env bash
set -euo pipefail

: "${NAMESPACE:?Set NAMESPACE}"
: "${IMAGE:?Set IMAGE to the API digest}"
: "${WORKER_IMAGE:?Set WORKER_IMAGE}"
: "${FRONTEND_IMAGE:?Set FRONTEND_IMAGE}"
components=(worker api frontend)
images=("$WORKER_IMAGE" "$IMAGE" "$FRONTEND_IMAGE")
# The worker can finish a ten-minute turn plus persistence before stopping.
rollout_timeouts=(15m 5m 5m)
previous=()
changed=()
for image in "${images[@]}"; do
  [[ "$image" =~ ^ghcr.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]] || {
    echo 'Deploy immutable GHCR image digests.' >&2
    exit 1
  }
done
for attempt in {1..12}; do
  if kubectl -n "$NAMESPACE" get deployment aimo-api --request-timeout=10s >/dev/null; then break; fi
  if [[ "$attempt" == 12 ]]; then
    echo 'Complete the one-time separate-app Terraform cutover first.' >&2
    exit 1
  fi
  sleep 5
done
# Refuse a partial/unbootstrapped installation before changing any component.
for component in "${components[@]}"; do
  replicas=$(kubectl -n "$NAMESPACE" get deployment "aimo-$component" -o jsonpath='{.spec.replicas}')
  [[ "$replicas" == 1 ]] || { echo "aimo-$component is not enabled." >&2; exit 1; }
  old=$(kubectl -n "$NAMESPACE" get deployment "aimo-$component" -o "jsonpath={.spec.template.spec.containers[?(@.name==\"$component\")].image}")
  test -n "$old"
  previous+=("$old")
done
# Always migrate, including same-image releases. Fail before installing the
# rollout recovery trap or changing any application image.
python3 "$(dirname "$0")/migrate-release.py"

# Releases only swap images, so pod-template additions made in Terraform after the
# one-time cutover never reach the cluster. Keep the API's voice-token key reference
# (identical to infra/kubernetes/main.tf) on every release. Strategic merge matches the
# container and variable by name, so an existing reference is a no-op; optional keeps
# the API starting when the worker Secret has no Google key.
kubectl -n "$NAMESPACE" patch deployment aimo-api --type=strategic -p '{"spec":{"template":{"spec":{"containers":[{"name":"api","env":[{"name":"GEMINI_API_KEY","valueFrom":{"secretKeyRef":{"name":"aimo-worker-runtime","key":"GEMINI_API_KEY","optional":true}}}]}]}}}}'

rollback() {
  trap - ERR
  echo 'Release failed; restoring all changed components.' >&2
  for index in "${changed[@]}"; do
    component=${components[$index]}
    kubectl -n "$NAMESPACE" set image "deployment/aimo-$component" "$component=${previous[$index]}" || true
  done
  for index in "${changed[@]}"; do
    kubectl -n "$NAMESPACE" rollout status "deployment/aimo-${components[$index]}" --timeout="${rollout_timeouts[$index]}" || true
  done
  exit 1
}
trap rollback ERR
for index in "${!components[@]}"; do
  component=${components[$index]}
  if [[ "${previous[$index]}" != "${images[$index]}" ]]; then
    # Track before mutation so an ambiguous API timeout still triggers restoration.
    changed+=("$index")
    kubectl -n "$NAMESPACE" set image "deployment/aimo-$component" "$component=${images[$index]}"
  elif [[ ( "$component" == worker || "$component" == api ) && ( "${LLM_REFRESHED:-false}" == true || "${SUPPLIER_REFRESHED:-false}" == true ) ]]; then
    # Both processes consume provider/supplier configuration from their startup environment.
    kubectl -n "$NAMESPACE" rollout restart "deployment/aimo-$component"
  fi
done
# Start the independent Deployments together, after migrations, then wait for all.
for index in "${!components[@]}"; do
  kubectl -n "$NAMESPACE" rollout status "deployment/aimo-${components[$index]}" --timeout="${rollout_timeouts[$index]}"
done
trap - ERR
printf 'Deployed frontend, API and worker.\n'

# Keep scheduled catalog sync on the released worker code. Absent when sync is not enabled.
# A failure here leaves the healthy apps deployed but fails the release visibly.
cron_image=$(kubectl -n "$NAMESPACE" get cronjob aimo-catalog-sync --ignore-not-found \
  --request-timeout=10s -o 'jsonpath={.spec.jobTemplate.spec.template.spec.containers[?(@.name=="catalog-sync")].image}')
if [[ -n "$cron_image" && "$cron_image" != "$WORKER_IMAGE" ]]; then
  kubectl -n "$NAMESPACE" set image cronjob/aimo-catalog-sync "catalog-sync=$WORKER_IMAGE" ||
    { echo 'Apps deployed, but the catalog-sync CronJob image was not updated.' >&2; exit 1; }
  printf 'Updated the catalog-sync CronJob image.\n'
fi
