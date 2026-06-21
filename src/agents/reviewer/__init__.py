"""Reviewer agent package (Sprint 6).

Exposes the SOLID/Clean-Code :class:`ReviewerAgent`, the deterministic PASS/FAIL
verdict rules, and the structured review-report schemas. The Reviewer is a
single-shot structured agent (project decision #2, like the Architect/Security
agents): the LLM emits review *comments*, but the gate-critical PASS/FAIL verdict
is computed deterministically from those comments' severities — see
``review_rules`` — so the ``review_decision`` edge never trusts LLM arithmetic.
"""
