"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
import functools
import inspect
import json
import re
from typing import Any, Dict, List, Optional
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result,
                     runtime_preamble)
from support import mock_backend as _backend          # Build 2: read-only data loaders
from support.tools import check_policy as _check_policy

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = """
=== DIFFICULT CUSTOMERS (Larkspur conversation triggers CONV-01, CONV-02) ===
- Abusive or threatening language (CONV-01), or any legal or regulatory threat
  such as a lawyer, a lawsuit or a complaint to a regulator (CONV-02): look up
  the booking, then call escalate_to_human. Start the reason with
  "priority high" and quote the customer's words verbatim in summary_for_human.
  Then reply with one calm message: acknowledge the complaint once and say a
  person will follow up. Do not argue or list entitlements, do not offer a
  refund, voucher or compensation, and promise nothing.
- A frustrated customer who is not abusive and makes no threat ("this is
  unacceptable", demands for more) is not CONV-01: stay calm and handle the
  request normally, including check_policy.
- Call issue_voucher only when the customer asks for a voucher or accepts your
  offer of one. If they ask what they are entitled to, tell them and offer it.
"""                                      # ✏️ Build 4, step 4.1, intelligence goal
# Build 2: both lists below are filled by "Our tools" at the bottom of this file.
EXTRA_TOOLS: List[Dict[str, Any]] = []   # ✏️ Build 2, step 2.1: schemas for the tools you add
LOCAL_TOOLS: Dict[str, Any] = {}         # ✏️ Build 2, step 2.1: the functions behind them


def text_of(response) -> str:
    """Given. The last non-empty text block, never content[0]."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text" and b.text]
    return texts[-1] if texts else ""


def tool_results(response) -> List[Dict[str, Any]]:
    """Given. Runs every tool_use block and packages the results the way the
    API expects them back. A tool can live in three places: the MCP server,
    LOCAL_TOOLS, or support/tools.py."""
    # three branches, no try/except in this file: mcp_client.call_remote() and
    # support.call_local() answer with an error dict instead of raising, and both
    # record what came back on the trace
    results = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name in mcp_client.tool_names:
            output = mcp_client.call_remote(block.name, block.input)
        elif block.name in LOCAL_TOOLS:
            output = call_local(LOCAL_TOOLS[block.name], block.name, block.input)
        else:
            output = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        })
    return results


def run_agent(pnr: str, last_name: str, message: str) -> str:            # ✏️ Build 1, step 1.2
    """Run the tool loop until Claude stops asking for tools. Return its final text."""
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    return text_of(response)


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Given. Exactly what Claude is offered on every turn; run.py --show-tools
    prints this list."""
    return build_tools() + EXTRA_TOOLS + mcp_client.tools()   # Build 2.2: + the MCP server's tools


# ──────────────────────────────────────────────────────────────────────────────
# Below this line: what Claude is told about each tool. Step 1.3.
# The functions these describe are written and correct, in support/tools.py.
# ──────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and the passenger's last name. Both are required to prevent a lookup on "
                "a guessed PNR. Returns fare family, loyalty tier, the segment that needs "
                "attention, and any group/partner/minor/SSR flags relevant to scope."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "last_name": {"type": "string"}},
                "required": ["pnr", "last_name"],
            },
        },
        {
            "name": "get_flight_status",
            "description": (
                "Look up a Larkspur or Larkspur Link flight's current OpsFeed status for "
                "one local date: status, delay minutes, and cause. Use this before telling "
                "a customer anything about a flight's timing; never state it from memory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {"type": "string", "description": "Flight number as on the booking, e.g. 'LK415'."},
                    "date": {"type": "string", "description": "Local departure date in ISO format YYYY-MM-DD, e.g. '2025-05-08'. Not MM/DD/YYYY."},
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            "name": "search_alternatives",
            "description": (
                "Find the rebooking options for the customer's disrupted segment (cancelled, "
                "delayed or missed connection): same route and cabin, enough seats for the "
                "party, with flight numbers, times, delay, seats left and fare difference, "
                "each with an option_id. Use it after the disruption is confirmed with "
                "get_flight_status, when the customer needs a new flight. Read-only: it does "
                "not hold or book anything. Pass an option_id to hold_seat to reserve one."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string", "description": "The booking's PNR (confirmation code), e.g. 'K7PQ2M'."}},
                "required": ["pnr"],
            },
        },
        {
            "name": "check_policy",
            "description": (
                "Resolve what Larkspur owes this customer for the disruption: rebooking "
                "waiver, refund path, meal/hotel/ground care, goodwill eligibility and cap, "
                "and any escalation triggers. cause_code, delay_minutes and status describe "
                "what get_flight_status told you; fare_family, loyalty_tier and whether this "
                "is overnight are looked up from the booking, not asked of you. Every "
                "response carries a policy_row_id. Cite it if you reference this decision "
                "again."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"},
                    "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"]},
                    "delay_minutes": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"]},
                    "wait_minutes_for_alternative": {"type": "integer"},
                    "chosen_option_id": {"type": "string"},
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": "Place a 15-minute hold on one alternative. Reversible. It simply expires.",
            "input_schema": {
                "type": "object",
                "properties": {"option_id": {"type": "string"}, "pnr": {"type": "string"}},
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat. Irreversible. Requires a confirmation_token that "
                "only the customer's own Confirm-click can produce. You cannot supply it "
                "yourself, and 'the customer said yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"hold_id": {"type": "string"}, "confirmation_token": {"type": "string"}},
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel, or goodwill voucher. Auto-approves within the "
                "policy's threshold for that type; above it, returns a pending status for a "
                "human. It does not fail. Always pass the policy_row_id that made it eligible."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "voucher_type": {"type": "string", "enum": ["meal", "ground", "hotel", "goodwill"]},
                    "amount_usd": {"type": "number"},
                    "pnr": {"type": "string"},
                    "policy_row_id": {"type": "string"},
                },
                "required": ["voucher_type", "amount_usd", "pnr", "policy_row_id"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand this conversation to a human, with your reasoning attached. Use for "
                "groups, partner segments, unaccompanied minors, refunds, or anything else "
                "out of scope. This is the correct outcome for those cases, not a failure."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"}, "reason": {"type": "string"},
                    "summary_for_human": {"type": "string"}, "queue": {"type": "string"},
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": "Send the customer a written confirmation of what was just done. Benign.",
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "message": {"type": "string"}},
                "required": ["pnr", "message"],
            },
        },
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Our tools (Build 2, step 2.1). Each one reads Larkspur's own files and never
# invents an answer: no record means it says so. Schemas go into EXTRA_TOOLS,
# functions into LOCAL_TOOLS, at the very end of this section.
# Step 2.2: next_available_day and fare_rules now come only from the MCP server
# (support/mcp_server.py, offered in tool_list()), so each name has one owner.
# ──────────────────────────────────────────────────────────────────────────────
_NOW = _backend.FIXTURE_CLOCK                    # the data's "now": 2025-05-08 14:10 MDT
_HORIZON = "%s to %s" % (_backend.DATA_HORIZON_START, _backend.DATA_HORIZON_END)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_FLIGHT_NO = re.compile(r"^LK\d{3,4}$")


class _InputError(ValueError):
    """Bad arguments from Claude. Comes back as {"error": ...} so it can retry."""


def _tool(fn):
    """A tool must never crash the loop. Bad input and unexpected failures both
    come back as an error Claude can read. Wrong argument names fail the
    signature check first, and call_local() reports that as "Bad arguments";
    any error after that is the tool's own, and is reported as such."""
    signature = inspect.signature(fn)

    @functools.wraps(fn)
    def wrapper(**kwargs):
        signature.bind(**kwargs)
        try:
            return fn(**kwargs)
        except _InputError as exc:
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001 - reported, never raised into the loop
            return {"error": "%s failed: %s: %s" % (fn.__name__, type(exc).__name__, exc)}
    return wrapper


def _date(value) -> str:
    value = str(value or "").strip()
    if not _ISO_DATE.match(value):
        raise _InputError("date must be YYYY-MM-DD, e.g. 2025-05-08. Got %r." % value)
    return value


def _airport(value, field: str = "airport") -> str:
    value = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise _InputError("%s must be a three-letter airport code, e.g. DEN. Got %r." % (field, value))
    return value


def _flight(value) -> str:
    value = re.sub(r"\s+", "", str(value or "")).upper()
    if not _FLIGHT_NO.match(value):
        raise _InputError("flight_no must look like LK415. Got %r." % value)
    return value


def _whole_number(value, field: str, minimum: int) -> int:
    """A count from Claude: 2 or "2" is fine; True, 2.9, "two" and negatives are not."""
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if not number.is_integer():
            raise ValueError
    except (TypeError, ValueError):
        raise _InputError("%s must be a whole number. Got %r." % (field, value)) from None
    if number < minimum:
        raise _InputError("%s must be %d or more. Got %r." % (field, minimum, value))
    return int(number)


def _clock(value, field: str) -> int:
    """'HH:MM' -> minutes after midnight."""
    value = str(value or "").strip()
    if not _HHMM.match(value):
        raise _InputError("%s must be 24-hour HH:MM, e.g. 17:00. Got %r." % (field, value))
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def _hhmm(total_minutes: int) -> str:
    """Minutes after midnight -> 'HH:MM', marking a slip past midnight."""
    day, rest = divmod(total_minutes, 1440)
    return "%02d:%02d%s" % (rest // 60, rest % 60, " (+%d day)" % day if day else "")


def _flight_row(flight_no: str, date: str) -> Optional[Dict[str, Any]]:
    return next((r for r in _backend.load_flights()
                 if r["flight_no"] == flight_no and r["date"] == date), None)


@functools.lru_cache(maxsize=1)
def _handbook() -> tuple:
    """fare_rules_excerpt.md split on its '### N. Title' headings."""
    text = (_backend.DATA_DIR / "fare_rules_excerpt.md").read_text(encoding="utf-8")
    sections = []
    for block in re.split(r"(?m)^### ", text)[1:]:
        heading, _, body = block.partition("\n")
        number, _, title = heading.strip().partition(". ")
        sections.append({"section": number, "title": title or heading.strip(),
                         "text": "### %s\n%s" % (heading.strip(), body.strip())})
    return tuple(sections)


@functools.lru_cache(maxsize=1)
def _transcripts() -> tuple:
    path = _backend.DATA_DIR / "transcripts_sample.jsonl"
    with open(path, encoding="utf-8") as fh:
        return tuple(json.loads(line) for line in fh if line.strip())


# (1. next_available_day and 2. fare_rules: served by the MCP server since step 2.2)


# ── 3. seats_left ────────────────────────────────────────────────────────────
@_tool
def tool_seats_left(flight_no, date, party_size=None):
    flight_no, date = _flight(flight_no), _date(date)
    row = _flight_row(flight_no, date)
    if row is None:
        return {"flight_no": flight_no, "date": date, "found": False,
                "note": "No record of %s on %s. The schedule covers %s." % (flight_no, date, _HORIZON)}
    sellable = row["status"] not in ("CANCELLED", "DIVERTED")
    result = {"flight_no": flight_no, "date": date, "route": "%s-%s" % (row["origin"], row["dest"]),
              "status": row["status"], "delay_min": row["delay_min"],
              "seats_left_main": row["seats_left_Y"], "seats_left_first": row["seats_left_J"],
              "as_of": _NOW.isoformat(),
              "note": "Open seats right now, not reserved. Only hold_seat reserves one."}
    if not sellable:
        result["note"] = "This flight is %s, so none of its seats can be sold." % row["status"]
    if party_size is not None:
        party = _whole_number(party_size, "party_size", 1)
        result.update({"party_size": party,
                       "fits_in_main": sellable and row["seats_left_Y"] >= party,
                       "fits_in_first": sellable and row["seats_left_J"] >= party})
    return result


# ── 4. departures_in_window ──────────────────────────────────────────────────
@_tool
def tool_departures_in_window(airport, date, earliest="00:00", latest="23:59", dest=None):
    airport, date = _airport(airport), _date(date)
    start, end = _clock(earliest, "earliest"), _clock(latest, "latest")
    if start > end:
        raise _InputError("earliest (%s) is after latest (%s)." % (earliest, latest))
    dest = _airport(dest, "dest") if dest else None
    now_min = _NOW.hour * 60 + _NOW.minute if date == _NOW.strftime("%Y-%m-%d") else None
    leaving, cancelled = [], []
    for row in _backend.load_flights():
        if row["origin"] != airport or row["date"] != date or (dest and row["dest"] != dest):
            continue
        sched = _clock(row["sched_dep_local"], "sched_dep_local")
        if row["status"] == "CANCELLED":
            if start <= sched <= end:
                cancelled.append({"flight_no": row["flight_no"], "dest": row["dest"],
                                  "sched_dep": row["sched_dep_local"], "cause_code": row["cause_code"]})
            continue
        est = sched + row["delay_min"]
        if not start <= est <= end:
            continue
        leaving.append({"flight_no": row["flight_no"], "dest": row["dest"],
                        "sched_dep": row["sched_dep_local"], "est_dep": _hhmm(est),
                        "status": row["status"], "delay_min": row["delay_min"],
                        "seats_left_main": row["seats_left_Y"], "seats_left_first": row["seats_left_J"],
                        "departed_by_now": now_min is not None and est < now_min})
    leaving.sort(key=lambda f: _clock(f["est_dep"][:5], "est_dep") + (1440 if "+" in f["est_dep"] else 0))
    return {"airport": airport, "date": date, "window_local": "%s-%s" % (earliest, latest),
            "as_of": _NOW.isoformat(), "departures": leaving, "cancelled_in_window": cancelled,
            "note": ("Times are local to %s; the window is matched on the estimated departure. "
                     "Larkspur flights only. An empty list means none in the data." % airport)}


# ── 5. ground_stop_status ────────────────────────────────────────────────────
_STOP_WINDOW = re.compile(r"ground stop\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*([A-Z]{3,4})?", re.I)


@_tool
def tool_ground_stop_status(airport):
    airport = _airport(airport)
    today = _NOW.strftime("%Y-%m-%d")
    known = {r["origin"] for r in _backend.load_flights()} | {r["dest"] for r in _backend.load_flights()}
    citing, window = [], None
    for row in _backend.load_flights():
        remark = row["remarks"]
        cut = remark.lower().find("ground stop")
        if row["date"] != today or cut < 0:
            continue
        # The stopped airport is the last real airport code written before "ground stop"
        # ("held at BNA (DEN GDP then ground stop ...)" is a DEN stop, not BNA).
        codes = [c for c in re.findall(r"\b[A-Z]{3}\b", remark[:cut]) if c in known]
        if not codes or codes[-1] != airport:
            continue
        citing.append({"flight_no": row["flight_no"], "status": row["status"], "remark": remark})
        found = _STOP_WINDOW.search(remark)
        if found and window is None:
            window = found.groups()
    if not citing:
        return {"airport": airport, "date": today, "ground_stop_recorded": False,
                "note": "No ground stop at %s appears in today's OpsFeed remarks. That is what "
                        "the data shows, not a promise about the airport." % airport}
    result = {"airport": airport, "date": today, "as_of": _NOW.isoformat(),
              "ground_stop_recorded": True, "flights_citing_it": citing,
              "note": "From OpsFeed remarks. A published end time is an estimate and can move."}
    if window is None:
        result["window_local"] = None
        result["note"] += " No start or end time is recorded, so do not give one."
        return result
    start, end, zone = window
    result["window_local"] = "%s-%s %s" % (start, end, zone or "")
    if (zone or "").upper() == "MDT" and _NOW.utcoffset().total_seconds() == -6 * 3600:
        now_min = _NOW.hour * 60 + _NOW.minute
        s, e = _clock(start.zfill(5), "start"), _clock(end.zfill(5), "end")
        result["in_effect_now"] = s <= now_min < e
        result["minutes_remaining"] = max(0, e - now_min) if s <= now_min < e else 0
    else:
        result["note"] += (" The recorded times carry no timezone this system can match to "
                           "now, so do not say whether the stop is still in effect.")
    return result


# ── 6. cause_in_plain_words ──────────────────────────────────────────────────
@_tool
def tool_cause_in_plain_words(cause_code, language="en"):
    policy = _backend.load_policy()
    labels = policy["cause_labels_customer"]
    code = str(cause_code or "").strip().upper()
    if code not in labels:
        raise _InputError("cause_code must be one of %s (get it from get_flight_status). Got %r."
                          % (", ".join(sorted(labels)), cause_code))
    language = str(language or "en").strip().lower()
    if language not in labels[code]:
        raise _InputError("language must be one of %s. Got %r." % (", ".join(sorted(labels[code])), language))
    cause_class = policy["cause_classes"][code]
    return {"cause_code": code, "say": labels[code][language], "language": language,
            "within_our_control": cause_class == "controllable", "cause_class": cause_class,
            "note": "Name the cause with exactly these words (Handbook section 5); do not add detail."}


# ── 7. hold_time_left ────────────────────────────────────────────────────────
@_tool
def tool_hold_time_left(hold_id):
    hold_id = str(hold_id or "").strip().upper()
    if not hold_id:
        raise _InputError("hold_id is required, e.g. HOLD-1A2B3C (from hold_seat).")
    # The backend has no getter, so this peeks at its in-memory holds. Read only.
    if hold_id in _backend._confirmed:
        return {"hold_id": hold_id, "status": "confirmed",
                "note": "This hold was already confirmed by the customer. Nothing is pending."}
    hold = _backend._holds.get(hold_id)
    if hold is None:
        return {"hold_id": hold_id, "status": "not_found",
                "note": "No hold with that id. Holds come from hold_seat and last %d minutes."
                        % _backend.HOLD_TTL_MINUTES}
    seconds = (hold["expires_at"] - _NOW).total_seconds()
    return {"hold_id": hold_id, "option_id": hold["option_id"],
            "status": "active" if seconds > 0 else "expired",
            "minutes_left": max(0, int(seconds // 60)), "expires_at": hold["expires_at"].isoformat(),
            "note": "Released automatically at expiry. Only the customer's Confirm click keeps it."}


# ── 8. what_automation_will_not_do ───────────────────────────────────────────
@_tool
def tool_what_automation_will_not_do():
    section = next((s for s in _handbook() if "will not do" in s["title"].lower()), None)
    if section is None:
        raise _InputError("The Handbook section on chat limits is missing from this copy.")
    return {**section, "source": "Larkspur Handbook v14.3, section %s" % section["section"],
            "note": "Explain the limit, then offer the hand-over (escalate_to_human) for the part a person does."}


# ── 9. reopen_stats ──────────────────────────────────────────────────────────
@_tool
def tool_reopen_stats(intent=None, disruption=None):
    rows = list(_transcripts())
    intents = sorted({r["intent_label"] for r in rows})
    if intent:
        rows = [r for r in rows if r["intent_label"] == str(intent).strip().lower()]
    if disruption:
        rows = [r for r in rows if (r.get("disruption") or {}).get("status") == str(disruption).strip().upper()]
    if not rows:
        return {"sample_size": 0, "available_intents": intents,
                "note": "No past chat in the sample matches that filter. Do not estimate."}
    reopened = [r for r in rows if r.get("reopened_within_72h")]
    return {"sample_size": len(rows), "reopened_within_72h": len(reopened),
            "summary": "%d of %d" % (len(reopened), len(rows)),
            "why_they_came_back": [r["reopen_reason"] for r in reopened if r.get("reopen_reason")],
            "filters": {"intent": intent, "disruption": disruption},
            "caveat": ("A hand-read sample of %d chats handled by people. Too small for a "
                       "forecast: describe what happened in past cases, never a probability "
                       "for this customer." % len(_transcripts()))}


# ── 10. care_entitlements ────────────────────────────────────────────────────
@_tool
def tool_care_entitlements(pnr, wait_minutes_for_alternative=None):
    pnr = str(pnr or "").strip().upper()
    if wait_minutes_for_alternative is not None:
        wait_minutes_for_alternative = _whole_number(
            wait_minutes_for_alternative, "wait_minutes_for_alternative", 0)
    try:
        booking = _backend.get_booking_raw(pnr)
    except _backend.NotFound as exc:
        raise _InputError(str(exc))
    # Everything is derived from the booking and OpsFeed, never from the chat,
    # the same guardrail check_policy keeps for fare family and tier.
    seg = _backend.get_disrupted_segment(booking)
    live = _backend.get_flight_status_raw(seg["flight_no"], seg["date"])
    status = live.get("status")
    base = {"pnr": pnr, "flight_no": seg["flight_no"], "date": seg["date"], "status": status,
            "passengers": len(booking["passengers"])}
    if status in (None, "NOT_IN_HORIZON") or "error" in live:
        return {**base, "care": None, "note": "No live status for this segment, so no care can be worked out."}
    if status == "ON_TIME":
        return {**base, "care": None, "note": "The flight is on time, so no care applies."}
    decision = _check_policy(pnr=pnr, cause_code=live["cause_code"], delay_minutes=live["delay_min"],
                             status=status, wait_minutes_for_alternative=wait_minutes_for_alternative)
    if "error" in decision:
        return {**base, **decision}
    return {**base, "delay_min": live["delay_min"], "cause_code": live["cause_code"],
            "policy_row_id": decision["policy_row_id"], "care_per_passenger": decision["care"],
            "note": ("Meal, hotel and ground care per passenger (Handbook section 6). Issue a voucher "
                     "only with issue_voucher and this policy_row_id. Rebooking, refunds and "
                     "goodwill are in check_policy.")}


# ── What Claude is told about our tools ──────────────────────────────────────
_OUR_TOOLS = [
    (tool_seats_left, {
        "name": "seats_left",
        "description": (
            "Count the open seats on ONE named Larkspur flight on one date, per cabin, and say "
            "whether a party of a given size fits. Use it when the customer names a flight and "
            "asks if there is room ('is there still space for the three of us on LK417?'). To "
            "find which flights to offer, use search_alternatives instead. Open seats are not "
            "reserved: only hold_seat reserves one."
        ),
        "input_schema": {"type": "object", "properties": {
            "flight_no": {"type": "string", "description": "Larkspur flight number, e.g. LK417."},
            "date": {"type": "string", "description": "Local departure date, YYYY-MM-DD, e.g. 2025-05-08."},
            "party_size": {"type": "integer", "description": "How many travel together; use passenger_count from lookup_booking. Optional."},
        }, "required": ["flight_no", "date"]},
    }),
    (tool_departures_in_window, {
        "name": "departures_in_window",
        "description": (
            "List every Larkspur flight leaving one airport on one date inside a time window, "
            "with estimated departure, status, delay and open seats, plus the ones cancelled in "
            "that window. Use it for open questions about an airport's board: 'what is still "
            "leaving Denver this afternoon?'. It is not tied to the customer's booking; for "
            "rebooking options on their own route use search_alternatives."
        ),
        "input_schema": {"type": "object", "properties": {
            "airport": {"type": "string", "description": "Departure airport, 3-letter code, e.g. DEN."},
            "date": {"type": "string", "description": "Local date, YYYY-MM-DD, e.g. 2025-05-08."},
            "earliest": {"type": "string", "description": "Window start, local 24-hour HH:MM, e.g. 17:00. Defaults to 00:00."},
            "latest": {"type": "string", "description": "Window end, local 24-hour HH:MM, e.g. 20:00. Defaults to 23:59."},
            "dest": {"type": "string", "description": "Only flights to this airport, 3-letter code. Optional."},
        }, "required": ["airport", "date"]},
    }),
    (tool_ground_stop_status, {
        "name": "ground_stop_status",
        "description": (
            "Say whether an airport is under a ground stop right now and, when the data records "
            "it, the stop's start and end time and the minutes left, with the flights that cite "
            "it. Use it when the customer asks if an airport is still closed or shut down, or "
            "when it reopens. get_flight_status covers one flight; this covers the airport."
        ),
        "input_schema": {"type": "object", "properties": {
            "airport": {"type": "string", "description": "Airport, 3-letter code, e.g. DEN."},
        }, "required": ["airport"]},
    }),
    (tool_cause_in_plain_words, {
        "name": "cause_in_plain_words",
        "description": (
            "Turn a disruption cause code into the only customer wording Larkspur allows, and "
            "say whether it was within Larkspur's control. Use it whenever you tell a customer "
            "WHY a flight is delayed, cancelled or diverted, after get_flight_status gave you the "
            "cause_code. Never describe a cause in your own words."
        ),
        "input_schema": {"type": "object", "properties": {
            "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"], "description": "The cause_code from get_flight_status."},
            "language": {"type": "string", "enum": ["en", "es"], "description": "The customer's language from lookup_booking. Defaults to en."},
        }, "required": ["cause_code"]},
    }),
    (tool_hold_time_left, {
        "name": "hold_time_left",
        "description": (
            "Say how many minutes are left on a seat hold before it is released, or whether it "
            "already expired or was confirmed. Use it when the customer asks how long they have "
            "to decide, after hold_seat has returned a hold_id. It changes nothing."
        ),
        "input_schema": {"type": "object", "properties": {
            "hold_id": {"type": "string", "description": "The hold_id that hold_seat returned, e.g. HOLD-1A2B3C."},
        }, "required": ["hold_id"]},
    }),
    (tool_what_automation_will_not_do, {
        "name": "what_automation_will_not_do",
        "description": (
            "Return Larkspur's written list of what this chat is not allowed to do and hands to "
            "a person (refunds, groups of 10 or more, hotel approval, other airlines, partner "
            "flights, unaccompanied minors, pets, medical, baggage). Use it when the customer "
            "asks you to do something you may not do, so you can explain the limit in "
            "Larkspur's words before handing over. Takes no input."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }),
    (tool_reopen_stats, {
        "name": "reopen_stats",
        "description": (
            "Report how often past disruption chats, handled by people, had to be reopened "
            "within 72 hours, and why, from a small hand-read sample. Use it when the customer "
            "asks if the problem will come back or whether they will have to contact Larkspur "
            "again. It describes past cases only; never present it as a prediction."
        ),
        "input_schema": {"type": "object", "properties": {
            "intent": {"type": "string", "description": "Optional filter, e.g. rebook_after_cancellation, missed_connection, refund_vs_credit, compensation_hotel_request."},
            "disruption": {"type": "string", "enum": ["CANCELLED", "DELAYED", "DIVERTED"], "description": "Optional filter on what happened to the flight."},
        }},
    }),
    (tool_care_entitlements, {
        "name": "care_entitlements",
        "description": (
            "Answer 'do I get a meal, a hotel or a ride while I wait?' for this booking: the "
            "meal, hotel and ground-transport care per passenger, worked out from the booking "
            "and live flight status (never from what the customer claims), with its "
            "policy_row_id. Use it for care-while-waiting questions. For rebooking, refunds or "
            "goodwill, use check_policy."
        ),
        "input_schema": {"type": "object", "properties": {
            "pnr": {"type": "string", "description": "The booking code (PNR)."},
            "wait_minutes_for_alternative": {"type": "integer", "description": "Minutes until the customer's new flight leaves, if known. Some meal credits depend on it."},
        }, "required": ["pnr"]},
    }),
]

EXTRA_TOOLS.extend(schema for _fn, schema in _OUR_TOOLS)
LOCAL_TOOLS.update({schema["name"]: fn for fn, schema in _OUR_TOOLS})
