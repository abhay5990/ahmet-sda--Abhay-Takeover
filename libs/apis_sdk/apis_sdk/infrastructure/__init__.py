"""
Infrastructure layer — technical runtime building blocks.

Contains HTTP transport, proxy pool/rotation engine, retry policies,
rate limiting, auth helpers, and logging adapters.

This layer depends only on core. It provides reusable technical
capabilities that client implementations build on top of.
"""
