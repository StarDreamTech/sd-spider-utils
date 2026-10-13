"""Vendored ModelTrace scoring; requires the optional NumPy dependency."""

from .fingerprint import analyze_global_outputs, generate_challenges, load_bank

__all__ = ["analyze_global_outputs", "generate_challenges", "load_bank"]
