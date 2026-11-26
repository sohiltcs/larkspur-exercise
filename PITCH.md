# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: A Larkspur disruption chat agent on Claude: the 9 given tools, 8 tools we wrote that only read Larkspur's own files, and 2 tools served by an MCP server.
Does: Looks up the booking, checks the live flight and the policy row, explains what the customer is owed, holds a seat for 15 minutes, and hands groups and refunds to a person.
Number: 13,430 to 24,688 tokens in per contact (average of the 5 ticket types, Build 1 vs Build 2), because the tool list now costs 4,983 tokens on every turn.
Safety check: 9 evals, 6 of them hard gates; 6 of 9 pass today and the release is blocked by tone_safety and handoff_quality.
Next: Stop the agent issuing vouchers nobody asked for, escalate abuse and legal threats, and show both legs of a connection.
Still broken: On a missed connection (T9WN4C) the agent never sees the inbound Sacramento flight, so it tells two people their Nashville connection may still work when it cannot be made.
Lever: intelligence

## Priya asked

Costs: Not priced yet; today we can show tokens, 24,688 tokens in per contact, and bench.py gives the cost per contact in Build 4.
Wrong: Every change is re-run against 8 fixed evals graded by rules and a separate judge model; one failed hard gate blocks the release.
Runs it: Proposed: Larkspur contact-center operations owns the agent; everything it may not do goes to a human queue, such as the Group Desk (GRP1).
Left out: Voice, refunds, group bookings, other airlines and hotel approval stay with people; the agent explains and hands over.
