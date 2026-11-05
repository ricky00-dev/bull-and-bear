"""Generation progress derived from durable events, independent of user judgments."""
import json


def generation_progress(events, *, terminal=None, mode="debate"):
    accepted = set()
    phase = "preparation"
    moderator = "not_started"
    extra_pending = False
    graph_engine = False
    fixed_rounds = False
    for event in events:
        kind = event["type"]
        data = json.loads(event["data"])
        graph_engine |= data.get('engine') == 'langgraph'
        fixed_rounds |= data.get('debate_flow') == 'fixed_three_rounds'
        if kind == "turn_started":
            phase = "statements"
        elif kind == "statement_accepted":
            accepted.add((data["side"], data["round"]))
        elif kind == "extra_round_requested":
            phase, moderator, extra_pending = "statements", "waiting", True
        elif kind == "moderator_started":
            phase, moderator, extra_pending = "moderator", "running", False
        elif kind == "debate_completed":
            terminal = "completed"
        elif kind == "debate_failed":
            terminal = "interrupted" if data.get("error", {}).get("reason") == "worker_restart" else "failed"
            if data.get('graph_status') in ('abstained', 'round_limit'):
                moderator = data['graph_status']
    base_complete = all((side, stage) in accepted for side in ("bull", "bear")
                        for stage in ("opening", "rebuttal", "closing"))
    if graph_engine and not fixed_rounds:
        base_complete = all((side, 'opening') in accepted for side in ('bull', 'bear'))
    if terminal == "completed":
        moderator, phase = "completed", "completed"
    elif terminal in ("failed", "interrupted") and moderator == "running":
        moderator = terminal
    return {"stage": phase, "base_rounds_complete": base_complete,
            "debate_complete": base_complete and not extra_pending if mode == "debate" else None,
            "moderator_status": moderator}
