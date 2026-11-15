"""Bounded parallel catalog reads; all session changes stay on the runner thread."""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from copy import deepcopy
from itertools import islice

from aimo.agent_limits import PARALLEL_READS
from aimo.agent_provider import check_deadline
from aimo.agent_stop import call_key
from aimo.agent_tools import ToolSession
from aimo.observability import log_context

MAX_PARALLEL_READS = 4
RECIPE_READS = frozenset({"search_recipes", "get_recipe"})


def executions(session, calls, deadline, live, progress, *, max_errors, round_number):
    """Yield outcomes in model order, with mutations as barriers between read groups.

    A child owns its caches and handlers. Failed/cancelled/late reads cannot mutate the
    live session. Context is copied separately per task for turn/round log correlation.
    Only one bounded group is submitted at a time; reads never retry automatically.
    """
    session.begin_reply()
    pending = iter(calls)
    carry = next(pending, None)
    while carry is not None:
        group = [carry]
        if carry.function.name in PARALLEL_READS:
            for call in islice(pending, min(MAX_PARALLEL_READS, max_errors) - 1):
                if call.function.name not in PARALLEL_READS or (
                    (call.function.name in RECIPE_READS)
                    != (group[0].function.name in RECIPE_READS)
                ):
                    carry = call
                    break
                group.append(call)
            else:
                carry = next(pending, None)
        else:
            carry = next(pending, None)

        executor = (
            ThreadPoolExecutor(max_workers=len(group))
            if group[0].function.name in PARALLEL_READS
            else None
        )
        jobs = []
        reads = {}
        try:
            for call in group:
                check_deadline(deadline)
                live()
                name = call.function.name
                phase_now = session.phase if session.phases_on and session.enforce_phases else None
                refusal = session.discipline(
                    name, call.function.arguments, parallel=name in PARALLEL_READS
                )
                if refusal is not None:  # never executed: the model reads the plain reason
                    jobs.append((call, None, refusal))
                    continue
                if name in RECIPE_READS:
                    session.recipe_discovery_started = True
                progress.emit("tool_started", name if name in session.registry else None)
                if executor:
                    key = (name, call.function.arguments)
                    if key not in reads:
                        child = ToolSession(session.identity, session.service)
                        child.products = deepcopy(session.products)
                        child.search_results = deepcopy(session.search_results)
                        child.recipe_details = deepcopy(session.recipe_details)
                        child.recipe_discovery_started = session.recipe_discovery_started
                        child.plan = deepcopy(session.plan)
                        context = copy_context()
                        future = executor.submit(
                            context.run, invoke, child, call, round_number, phase_now
                        )
                        reads[key] = (child, future)
                    child, future = reads[key]
                    jobs.append((call, child, future))
                else:
                    jobs.append((call, session, None))
            for call, child, future in jobs:
                error = None
                result = None
                try:
                    if child is None:
                        raise future  # a refusal made before execution
                    if future:
                        while True:
                            live()
                            remaining = check_deadline(deadline)
                            try:
                                result = future.result(timeout=min(0.25, remaining))
                                break
                            except TimeoutError:
                                # A tool can itself raise TimeoutError; don't poll it forever.
                                if future.done():
                                    raise
                    else:
                        result = invoke(session, call, round_number, phase_now_of(session))
                except Exception as exc:
                    error = exc
                # Cancellation/reclaim must win even after an already-finished read.
                live()
                if error is None and child is not session:
                    session.products.update(child.products)
                    session.search_results.update(child.search_results)
                    session.recipe_details.update(child.recipe_details)
                yield call, result, error
                if error is not None:
                    max_errors -= 1
                    if max_errors <= 0:
                        return
        finally:
            if executor:
                # Running work is read-only and isolated. Never wait past the turn budget.
                executor.shutdown(wait=False, cancel_futures=True)


def phase_now_of(session):
    return session.phase if session.phases_on and session.enforce_phases else None


def invoke(session, call, round_number, phase=None):
    with log_context(
        round=round_number,
        tool=call.function.name if call.function.name in session.registry else "unavailable",
        args_fingerprint=call_key(call.function.name, call.function.arguments)[1],
        **({"phase": phase} if phase else {}),
    ):
        return session.invoke(call.function.name, call.function.arguments)
