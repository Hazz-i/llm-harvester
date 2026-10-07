"""Backward-compatibility shim redirecting to llmharvester."""
import sys
import llmharvester

# Re-export all attributes from llmharvester
for _attr in dir(llmharvester):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(llmharvester, _attr)

sys.modules[__name__] = llmharvester
