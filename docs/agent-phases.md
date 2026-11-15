# Agent phases

Server-owned phases for the agent turn, on top of the stop control (`docs/agent-stop-control.md`). One switch:
`AGENT_PHASES` (default `true`; needs `AGENT_STOP_CONTROL`; `false` restores the earlier prompt, tools and
guidance). The agent never confirms or purchases in any phase: it only updates the card; the customer's
button commits (TCT-007, CNF-003). Code: `ToolSession.phase`, `hidden_tools`, `phase_refusal`,
`phase_guidance` (`src/aimo/agent_tools.py`), `PHASE_HIDDEN` (`src/aimo/agent_stop.py`), `agent.run_turn`.

## The phase is derived, never stored
Recomputed every round from state the session already holds: the plan (none, incomplete, complete), recipe
discovery, a prepared basket, a plan restored from an earlier turn, and the customer's message (an explicit
advice cue, a request to buy, or the card-edit line "I changed the cart on the card ..."). It is logged per
round (`phase` in the round's log context) and as `phase_path` in `agent.turn.ended`.

| Phase | Derived when | Hidden tools | Guidance (one line) |
|---|---|---|---|
| understand | no plan, no recipe discovery | match_ingredient(s), prepare_order | classify (advice / shopping / card edit / status); at most one refining question for missing core facts (ingredients/date/destination); recipe optional once ingredients are known |
| recipe | recipe discovery started, no plan | match_ingredient(s), prepare_order (catalog tools wait for the plan, as before) | publish the quantity plan now (free-form ingredients, scale_recipe or draft_recipe) |
| match | a plan with unmatched items | scale_recipe, draft_recipe, prepare_order | N unmatched: search together, save the matches in ONE call |
| prepare | plan complete, no basket, and the plan changed this turn, or a buy request, or a card edit | recipe and match tools, get_recipe_plan | call prepare_order now; defaults are Helsinki today plus three days and the policy destination (card-editable); chat may still refine them |
| finish | a basket was prepared this turn | everything except get_proposal/get_order, tools the customer names, the policy when blocked | 2 to 4 sentences: what was prepared, what is not included, review the exact basket and press Confirm purchase; never "purchased" |
| advice | an explicit advice cue | prepare_order, publish_meal_plan | answer directly, no basket |
| open | an unchanged plan from an earlier turn and no request | nothing | answer; tools only if needed |

Advice wins when unsure; nothing is ever confirmed, so a wrong "shopping" costs an unwanted draft card, not an order.

## Enforcement and safety
Phases are enforced by the turn runner only. A hidden tool is not shown and, if called, answers
`TOOL_NOT_ALLOWED` naming the phase and the available tools (after the arguments were validated; parallel
reads are checked by the parent before dispatch). **Two phase refusals widen the restrictions for the rest of
the turn**, so a wrongly derived phase is never a dead end. Core chat facts stay ingredients, date and
destination; defaults fill open date/destination while refining questions remain allowed. No new tool,
no migration, no contract change.

## Continuation
With phases on, a complete plan without a basket is continued ONCE even without a buy word and even when the
reply mentions a date (no plan-only mode); the rest of the stop-control conditions (rounds, 15 s, input check
allowed, prepare not refused) are unchanged. `cart_purchase.auto_prepare` remains the server's backstop.

## Not built
Buttons / `ask_choice` and automatic result blocks; a stored phase (AGH-015 is reworded to "derived each
round and recorded in the turn's log"); CLARIFY beyond one plain question (Q-130 pending: it is the one-line
`PHASE_ONE_QUESTION`).
