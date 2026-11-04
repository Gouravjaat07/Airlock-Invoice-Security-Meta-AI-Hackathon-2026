"""Replaceable adapters: readers, vision, transcription, explainers, payments.

Phase 2 defaults are deterministic local doubles (fixture reader, mock SAM,
mock ASR, template explainer, mock executor). No adapter performs network
I/O in the default configuration.
"""
