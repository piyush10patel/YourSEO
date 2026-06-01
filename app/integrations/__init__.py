"""External data providers (spec §14/§18/§19).

Behind narrow Protocol interfaces so real vendors (Semrush, Ahrefs, GSC, ...)
can be dropped in later. Until API keys are configured, deterministic *stub*
implementations return clearly-labeled placeholder data so the rest of the
system (keyword enrichment, the Authority agent, SERP views) works end to end.
"""
