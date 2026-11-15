# Agent stop control

The agent loop ends when the model replies without a tool call. This adds server-owned steering so a turn
stops when the request is done and does not stop short when the customer asked to buy. One switch:
`AGENT_STOP_CONTROL` (default `true`; `false` restores the earlier behaviour for guidance, refusals and the
continuation; the end-of-turn log line is always written). Guardrails, the confirmation gate and every fixed
rule are unchanged; the keyword sets only steer the assistant's next step, never authorize anything.
Code: `src/aimo/agent_stop.py`, `ToolSession.execution_guidance/discipline`, `agent.run_turn`.

| Part | What happens |
|---|---|
| Guidance (every round) | Basket prepared in this turn: "do not call more tools, reply briefly, point to Confirm purchase" (blocked basket: explain the blocker, the policy lookup stays allowed). Customer asked to buy (a REQUEST: imperative or "I want to / please / let's / go ahead / can you order", or a need verb with a quantity; an acknowledgement reads the message before it; questions about ordering, negations, past orders and "confirm for me / approve it yourself" never count) and the plan is complete: "call prepare_order now or ask for the one missing fact". Explicit advice-only cue ("just asking", "älä tilaa", "bara fråga"): answer directly. |
| Tool discipline | After the basket: generate_recipe_image, manage_memory, search_recipes, draft_recipe, scale_recipe, get_purchase_policy are refused (`TOOL_NOT_ALLOWED`, plain reason) unless the customer's last message names them (policy stays allowed for a blocked basket). An identical call (tool plus hash of the canonical arguments) in a later reply of the same turn is refused (`TOOL_REPEATED`); state-reading tools are exempt; a call that failed may be retried. |
| Continuation | The model ends with no tool call, the customer asked to buy, the plan is complete, nothing was prepared, the input check was allowed (or guards off), prepare was not refused, rounds and 15 s remain, and the reply does not mention when, where or the delivery (stems en/fi/sv, no question mark needed) and the remaining time (read without raising) is at least 15 s: ONE labelled server notice, then the loop goes on. Never twice per turn. |
| Logs | `tool.call.started` carries `args_fingerprint` (16 hex, never the arguments). `agent.turn.ended`: `stop_reason` (answered, question, blocked, round_limit, time_limit, error), `continued_once`, `rounds`, `tool_calls`, `repeated_calls`, `calls_after_prepare`. |
| Fixed texts | The step-limit reply states the plan or basket status ("The plan has 3 of 5 ingredients matched; 2 still need a product." / "The basket is prepared; review it and press Confirm purchase."); the time-limit reply already states the plan status. |
