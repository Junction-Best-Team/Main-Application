# Runtime diagnostics

The API, worker and CLI emit structured JSON on `aimo.operations` to stderr.
No additional service, database table, dependency or debug switch is required.
Service operations already cover catalog/recipe search, supplier lookups, basket
preparation, confirmation and mock-order work. The same instrumentation now
correlates nested operations and records failures even when the application
recovers and returns a partial result.

## Find one failed conversation

Use the intended cluster's kubeconfig/context. Collect both API and worker logs:

```sh
kubectl -n junction logs -l 'app in (aimo-api,aimo-worker)' \
  --all-containers=true --prefix --since=30m --tail=-1 --max-log-requests=10
```

Each JSON event includes a timestamp, runtime ID and process ID; configured
entry points also identify `api`, `worker` or `cli`. Kubernetes' prefix supplies
the pod/container. Begin with `conversation_id`, then follow its `turn_id` and
`attempt_id`. `chat.queued` links the HTTP `request_id` to that turn. Retried or
reclaimed turns have new attempt IDs; never combine them as one attempt.
The browser's API error debug context includes `X-Request-ID`, including an
unexpected HTTP 500. `operation_id` and `parent_operation_id` link nested provider,
tool and service work, including parallel reads.

Read the following events in timestamp order:

| Area | Useful events and fields |
| --- | --- |
| HTTP | `http.request`: route template, status, duration, time to headers, response bytes/chunks, outcome, disconnect and response-complete flags. Validation and framework rejections have separate events. A stream can send HTTP 200 and subsequently have `outcome=error`; 200 alone is not success. |
| Queue/worker | `chat.queued`, `worker.claimed` (queue age, lease headroom), `worker.reclaimed`, `worker.attempt_limit`, `worker.readiness.failed`. |
| Agent/tools | `agent.thinking` (round), `tool.call.started/completed/failed`, `tool.group_started`, `tool.group_abandoned`, `agent.interrupted`, `agent.recovered`. Recovery identifies reviewed-plan vs persisted-result recovery; completion does not erase the original failure. |
| Google providers | `provider.google.*`: operation/model, configured timeout and byte limit, HTTP status, response bytes, timeout phase, allowlisted provider error, candidate/part/call counts, finish reasons, block reason and numeric token usage. Chat, guardrails, embedding/ranking, images and voice-token minting all use this boundary. |
| Legacy providers/supplier | Existing `llm.*`, `search.*`, `supplier.*` events retain response status/retries; `llm.response_shape` includes response bytes and call counts. Guardrail transport failures/retries keep their attempt and boundary. |
| Guardrails | `guardrail.decision`: boundary, verdict, policy/model, probabilities, failed/uncertain checks, calls used/limit and remaining turn time. It never supplies purchasing authority. |
| Persistence | `chat.context_loaded`, `chat.basket_recovered`, `chat.persisted` (partial flag, plan counts), `chat.execution_failed`, `chat.failure_state_failed`. If failure-state storage also fails, both errors are logged and the original exception is retained. |
| Database | Pool exhaustion, SQLSTATE/transaction failures and slow connections; slow events separate acquisition from transaction time. No SQL text or connection URL is logged. |
| Optional/recovered work | `attachment.*`, `image.*`, `voice.session.*`, cart auto-preparation and unreadable saved-plan events. Scheduled-run steps include run/authorization IDs and retries. |
| Process | API startup failure, worker readiness failure, `process.unhandled`, `thread.unhandled`, `async.unhandled`; failure summaries retain bounded exception-group and cause types/locations. |

Failure summaries include exception type, application error code/status, bounded
stack file/function/line locations and validation error types/counts. Adapter
translations using `raise ... from None` retain these safe root-cause details.
They never include exception messages, traceback source lines, locals, request
bodies, tool arguments, reasoning/signatures, customer text, audio, images,
credentials, SQL parameters, cookies or provider headers/bodies. Known sensitive
metadata keys are redacted defensively; call sites must still pass only safe
metadata. Records and exception chains are bounded. Logging/observer failures
must not change application results or repeat a paid request.

## Restarts and limits

For a restarted pod, inspect its previous container and Kubernetes state:

```sh
kubectl -n junction logs POD_NAME --previous --timestamps
kubectl -n junction describe pod POD_NAME
kubectl -n junction get events --sort-by=.lastTimestamp
```

A killed process, node loss or OOM cannot reliably emit a final Python event.
Use pod exit reasons/restart counts/events alongside the runtime ID and worker
reclaim events. This change does not install centralized retention or alerts;
stdout/stderr retention follows the cluster's existing configuration. Preserve
incident logs before rotation, with appropriate access controls. Browser-only
JavaScript/WebSocket failures and ingress failures are outside Python's boundary;
use the existing browser debug context and platform/browser diagnostics for those.
Do not enable raw HTTP/SQL/body debug logging to investigate them.

Verification uses authored transports and fixture databases, including partial
recovery, stream failures/cancellation, nested/parallel context, grouped errors,
private sentinel values and deliberately broken logging observers. It makes no
live model/supplier calls and authorizes no purchase.
