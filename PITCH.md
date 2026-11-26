# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: A Larkspur disruption chat agent on Claude: the 9 given tools, 8 tools we wrote that only read Larkspur's own files, and 2 tools served by an MCP server.
Does: Looks up the booking, checks the live flight and the policy row, explains what the customer is owed, holds a seat for 15 minutes, passes abuse and legal threats straight to a person, and hands groups and refunds to a person.
Number: 12 to 15 of 15 harder-ticket runs pass Larkspur's tool rules (5 harder tickets, 3 runs each), and the legal-threat ticket went from 0 to 3 of 3, at $0.0928 to $0.0923 model cost per contact.
Safety check: 9 evals, 6 of them hard gates; 8 of 9 pass after the change, and the release is still blocked by one: handoff_quality.
Next: Let the agent see both legs of a connection, then cut cost, because the timestamp at the top of the prompt stops caching.
Still broken: On a missed connection (T9WN4C) the agent never sees the inbound Sacramento flight, so it tells two people their Nashville connection may still work when it cannot be made.
Lever: intelligence

## Priya asked

Costs: $0.0923 model cost per contact (bench.py, model only, not loaded cost), about $1,265 a week at 13,700 chats a week; the change added no cost.
Wrong: Every change is re-run against 8 fixed evals graded by rules and a separate judge model; one failed hard gate blocks the release.
Runs it: Proposed: Larkspur contact-center operations owns the agent; everything it may not do goes to a human queue, such as the Group Desk (GRP1).
Left out: Voice, refunds, group bookings, other airlines and hotel approval stay with people; the agent explains and hands over.
