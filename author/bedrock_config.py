"""Configuration for the Bedrock-backed bdd-author step - all via environment variables.

Nothing here is secret; auth comes from your normal AWS credential chain (Okta SSO / AWS_PROFILE).
"""
from __future__ import annotations

import os

# Default model: a Claude Opus 4.x **cross-region inference profile** in APAC (Sydney = ap-southeast-2).
# The `au.` prefix keeps inference within the Australian region; `global.` is also available.
# Verified ACTIVE in account 484438948628 on 2026-06-26 (aws bedrock list-inference-profiles
# --region ap-southeast-2). To override:  $env:BDD_AUTHOR_BEDROCK_MODEL = '<the id>'
DEFAULT_MODEL = "au.anthropic.claude-opus-4-8"
DEFAULT_REGION = "ap-southeast-2"


def model_id() -> str:
    return os.environ.get("BDD_AUTHOR_BEDROCK_MODEL", DEFAULT_MODEL)


def region() -> str:
    return os.environ.get("BDD_AUTHOR_AWS_REGION") or os.environ.get("AWS_REGION") or DEFAULT_REGION


def profile() -> str | None:
    """Named profile to use; None falls back to the default AWS credential chain."""
    return os.environ.get("BDD_AUTHOR_AWS_PROFILE") or os.environ.get("AWS_PROFILE")


def max_tokens() -> int:
    return int(os.environ.get("BDD_AUTHOR_MAX_TOKENS", "8000"))
