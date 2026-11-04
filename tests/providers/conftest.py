"""Provider tests: isolation is global (see tests/conftest.py).

No per-directory fixtures needed; this file only documents that every
test under tests/providers/ runs with reset guards and cleared pool
transports, offline, with stub transports at the network boundary.
"""
