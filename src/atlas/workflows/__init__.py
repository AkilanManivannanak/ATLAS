"""End-to-end workflows composed from domain, rail, ledger and store packages."""

from .vertical_slice import VerticalSliceResult, run_vertical_slice

__all__ = ["VerticalSliceResult", "run_vertical_slice"]
