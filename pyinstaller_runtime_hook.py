import importlib.metadata as importlib_metadata
import sys


if getattr(sys, "frozen", False):
    _original_version = importlib_metadata.version

    def _safe_version(distribution_name):
        value = _original_version(distribution_name)
        if value is None and str(distribution_name).casefold() == "apscheduler":
            return "3.10.4"
        return value

    importlib_metadata.version = _safe_version
