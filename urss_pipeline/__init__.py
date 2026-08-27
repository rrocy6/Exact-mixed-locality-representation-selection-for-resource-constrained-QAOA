"""Deterministic smoke pipeline for the URSS benchmark data layer."""

from .generators import generate_max3sat, generate_spin_glass
from .identity import compute_instance_id
from .polynomial import max3sat_to_pubo, spin_glass_to_pubo
from .validation import validate_direct_vs_canonical, validate_raw_instance

__all__ = [
    "compute_instance_id",
    "generate_max3sat",
    "generate_spin_glass",
    "max3sat_to_pubo",
    "spin_glass_to_pubo",
    "validate_direct_vs_canonical",
    "validate_raw_instance",
]
