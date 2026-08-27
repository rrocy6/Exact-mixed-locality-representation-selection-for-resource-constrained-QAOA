"""Deterministic benchmark, representation, and reference-pilot utilities."""

from .generators import generate_max3sat, generate_spin_glass
from .formal_data import run_formal_data_pipeline
from .identity import compute_instance_id
from .polynomial import max3sat_to_pubo, spin_glass_to_pubo
from .reference_compiler import compile_reference
from .representations import fully_quadratize
from .step1_freeze import freeze_step1_config
from .validation import validate_direct_vs_canonical, validate_raw_instance

__all__ = [
    "compute_instance_id",
    "compile_reference",
    "fully_quadratize",
    "freeze_step1_config",
    "generate_max3sat",
    "generate_spin_glass",
    "max3sat_to_pubo",
    "run_formal_data_pipeline",
    "spin_glass_to_pubo",
    "validate_direct_vs_canonical",
    "validate_raw_instance",
]
