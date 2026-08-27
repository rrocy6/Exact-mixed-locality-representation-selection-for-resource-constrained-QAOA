"""Deterministic benchmark, representation, and reference-pilot utilities."""

from .generators import generate_max3sat, generate_spin_glass
from .e1_exactness import run_e1_exactness_pipeline
from .e2_resources import run_e2_resources_pipeline
from .e3_qaoa import run_e3_qaoa_pipeline
from .e4_warmstart import run_e4_warmstart_pipeline
from .e5_regime import run_e5_regime_pipeline
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
    "run_e1_exactness_pipeline",
    "run_e2_resources_pipeline",
    "run_e3_qaoa_pipeline",
    "run_e4_warmstart_pipeline",
    "run_e5_regime_pipeline",
    "run_formal_data_pipeline",
    "spin_glass_to_pubo",
    "validate_direct_vs_canonical",
    "validate_raw_instance",
]
