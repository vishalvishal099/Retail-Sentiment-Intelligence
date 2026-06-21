"""Outbound notification channels — Slack + Email + dispatcher.

All channels respect a per-channel `dry_run` flag: when set, the channel only
logs what it *would* send and returns a synthetic success. This is the default
so the pipeline can drive the lifecycle table before live secrets are wired.
"""
