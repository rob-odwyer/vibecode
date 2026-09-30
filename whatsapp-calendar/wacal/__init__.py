"""Glue library for the WhatsApp -> Google Calendar routine.

Deterministic plumbing only: fetching/normalising messages, tracking a
cursor, and upserting events into Google Calendar. The *reading* of
messages (deciding what is an event) is done by the agent that runs the
routine, not by this code.
"""
