"""Independent sign, endianness and uniform-input controls for E4."""

from __future__ import annotations

import math
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import yaml

from urss_pipeline import e4_warmstart as e4
from urss_pipeline.e2_resources import _evaluate_design
from urss_pipeline.e3_qaoa import (
    QAOABudgetSpec, QAOADesign, StatevectorData, simulate_qaoa,
    statevector_data, statevector_metrics,
)


def fixture_data(n: int) -> StatevectorData:
    indices = np.arange(1 << n)
    original = 0.4 * (indices % 4) - 0.7 * ((indices >> 1) % 2)
    encoded = original + 0.3 * indices + 0.2 * (indices % 3)
    return StatevectorData(encoded, original, (indices % 3 == 0).astype(float),
                           (original == original.min()).astype(float))


def dense_local_mixer(probability: float, beta: float) -> np.ndarray:
    """Independent Ry(theta) Rz(2 beta) Ry(-theta) matrix construction."""
    theta = 2 * math.asin(math.sqrt(probability))
    c, s = math.cos(theta / 2), math.sin(theta / 2)
    ry = np.array([[c, -s], [s, c]])
    rz = np.diag([np.exp(-1j * beta), np.exp(1j * beta)])
    return ry @ rz @ ry.T


class MixerCoordinateTests(unittest.TestCase):
    def test_local_operator_matches_independent_rotations(self):
        for probability in (0.0, 0.0025, 0.05, 0.2, 0.5, 0.7, 0.95, 1.0):
            for beta in (-0.63, 0.0, 0.37, 1.21):
                with self.subTest(probability=probability, beta=beta):
                    columns = []
                    for column in np.eye(2, dtype=complex).T:
                        state = column.copy()
                        e4._apply_matched_mixer(state, beta, (probability,))
                        columns.append(state)
                    actual = np.column_stack(columns)
                    np.testing.assert_allclose(actual, dense_local_mixer(probability, beta),
                                               rtol=0, atol=1e-12)
                    np.testing.assert_allclose(actual.conj().T @ actual, np.eye(2),
                                               rtol=0, atol=1e-12)

    def test_mixer_only_preserves_product_state_with_declared_phase(self):
        probabilities = (0.0, 0.05, 0.2, 0.5, 0.7, 1.0)
        initial = e4.product_state(probabilities)
        for beta in (-0.6, 0.0, 0.37):
            state = initial.copy()
            e4._apply_matched_mixer(state, beta, probabilities)
            np.testing.assert_allclose(state, np.exp(-1j * len(probabilities) * beta) * initial,
                                       rtol=0, atol=1e-12)

    def test_nonuniform_multilayer_matches_dense_little_endian_reference(self):
        probabilities = (0.2, 0.7, 0.05)
        gammas, betas = (0.37, -0.21), (-0.19, 0.61)
        data = fixture_data(3)
        state = np.array([1.0 + 0j])
        for probability in probabilities:
            state = np.kron([math.sqrt(1 - probability), math.sqrt(probability)], state)
        for gamma, beta in zip(gammas, betas):
            operator = np.array([[1.0 + 0j]])
            for probability in probabilities:
                operator = np.kron(dense_local_mixer(probability, beta), operator)
            state = operator @ (np.exp(-1j * gamma * data.encoded_energies) * state)
        actual = e4.simulate_warm_qaoa(data, probabilities=probabilities, gammas=gammas, betas=betas)
        np.testing.assert_allclose(actual, state, rtol=0, atol=1e-12)

    def test_qiskit_rotations_match_full_nonuniform_complex_state(self):
        from qiskit import QuantumCircuit
        from qiskit.circuit.library import DiagonalGate
        from qiskit.quantum_info import Statevector

        probabilities = (0.2, 0.7, 0.05)
        data = fixture_data(3)
        gammas, betas = (0.37, -0.21), (-0.19, 0.61)
        angles = [2 * math.asin(math.sqrt(value)) for value in probabilities]
        circuit = QuantumCircuit(3)
        for qubit, theta in enumerate(angles):
            circuit.ry(theta, qubit)
        for gamma, beta in zip(gammas, betas):
            circuit.append(DiagonalGate(np.exp(-1j * gamma * data.encoded_energies)), range(3))
            for qubit, theta in enumerate(angles):
                # Circuit append order is right-to-left in the matrix product.
                circuit.ry(-theta, qubit)
                circuit.rz(2 * beta, qubit)
                circuit.ry(theta, qubit)
        expected = np.asarray(Statevector.from_instruction(circuit))
        actual = e4.simulate_warm_qaoa(data, probabilities=probabilities, gammas=gammas, betas=betas)
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)

    def test_product_basis_order_is_little_endian(self):
        for probabilities, index in (((1, 0, 0), 1), ((0, 1, 0), 2), ((0, 0, 1), 4)):
            expected = np.zeros(8, dtype=complex)
            expected[index] = 1
            np.testing.assert_array_equal(e4.product_state(probabilities), expected)

    def test_uniform_input_matches_cold_state_probabilities_and_metrics(self):
        for n in (1, 3, 5):
            data = fixture_data(n)
            for gammas, betas in (((), ()), ((0.7,), (0.3,)), ((0.37, -0.21), (-0.19, 0.61))):
                with self.subTest(n=n, p=len(gammas)):
                    cold = simulate_qaoa(data, gammas=gammas, betas=betas)
                    warm = e4.simulate_warm_qaoa(data, probabilities=(0.5,) * n, gammas=gammas, betas=betas)
                    np.testing.assert_allclose(warm, cold, rtol=0, atol=1e-12)
                    np.testing.assert_allclose(np.abs(warm)**2, np.abs(cold)**2, rtol=0, atol=1e-12)
                    for field, value in statevector_metrics(cold, data).items():
                        self.assertAlmostEqual(statevector_metrics(warm, data)[field], value, places=12)

    def test_uniform_input_need_not_give_uniform_qaoa_output(self):
        values = np.array([0.0, 1.0])
        data = StatevectorData(values, values, np.zeros(2), np.array([1.0, 0.0]))
        state = e4.simulate_warm_qaoa(data, probabilities=(0.5,), gammas=(0.7,), betas=(0.3,))
        expected_one = (1 + math.sin(0.7) * math.sin(0.6)) / 2
        self.assertAlmostEqual(abs(state[1])**2, expected_one, places=12)
        self.assertGreater(abs(abs(state[1])**2 - 0.5), 0.1)


class NullControlGateTests(unittest.TestCase):
    def test_runtime_gate_passes_with_zero_differences(self):
        report = e4.require_uniform_null_control()
        self.assertEqual(report['status'], 'pass')
        self.assertEqual(report['comparisons'], 12)
        for field in ('max_state_error', 'max_probability_error', 'max_metric_error'):
            self.assertEqual(report[field], 0.0)

    def test_runtime_gate_rejects_legacy_beta_sign(self):
        original = e4._apply_matched_mixer
        with patch.object(e4, '_apply_matched_mixer',
                          side_effect=lambda state, beta, probabilities: original(state, -beta, probabilities)):
            with self.assertRaises(e4.E4WarmStartError):
                e4.require_uniform_null_control()

    def test_runtime_gate_rejects_relative_phase_corruption(self):
        original = e4._simulate
        def corrupt(data, spec, parameters, p):
            state = original(data, spec, parameters, p)
            if spec.policy != 'cold_start':
                state[0] *= 1j
            return state
        with patch.object(e4, '_simulate', side_effect=corrupt):
            with self.assertRaises(e4.E4WarmStartError):
                e4.require_uniform_null_control()

    def test_strong_bias_stops_before_creating_output_on_null_failure(self):
        from urss_pipeline import four_part_addendum as addendum
        with patch.object(addendum, 'require_uniform_null_control', side_effect=e4.E4WarmStartError('injected')), \
             patch.object(addendum, '_phase_start') as start:
            with self.assertRaises(e4.E4WarmStartError):
                addendum.run_strong_bias(repo=Path('.'), output_root=Path('unused'), config={},
                                         config_hash='', parent={}, code_commit='', resume=False)
            start.assert_not_called()

    def test_full_e4_stops_before_reading_inputs_on_null_failure(self):
        with patch.object(e4, 'require_uniform_null_control', side_effect=e4.E4WarmStartError('injected')), \
             patch.object(e4, 'verify_e4_inputs') as verify:
            with self.assertRaises(e4.E4WarmStartError):
                e4.run_e4_warmstart_pipeline(config_path='unused', config_hash_path='unused',
                    data_directory='unused', results_directory='unused', tables_directory='unused',
                    figures_directory='unused', code_commit='unused')
            verify.assert_not_called()

    def test_rejects_invalid_probability_width_and_parameter_layout(self):
        for probability in (-0.1, 1.1, math.nan, math.inf, -math.inf):
            with self.subTest(probability=probability), self.assertRaises(ValueError):
                e4.product_state((probability,))
        with self.assertRaises(ValueError):
            e4.simulate_warm_qaoa(fixture_data(3), probabilities=(0.5,), gammas=(), betas=())
        with self.assertRaises(ValueError):
            e4.simulate_warm_qaoa(fixture_data(3), probabilities=(0.5,)*3, gammas=(1,), betas=())
        invalid = StatevectorData(*(np.zeros(3) for _ in range(4)))
        with self.assertRaises(ValueError):
            e4.simulate_warm_qaoa(invalid, probabilities=(0.5,), gammas=(), betas=())
        spec = e4.WarmStartSpec('cold_start', 'not_applicable', None)
        for p, parameters in ((-1, ()), (2, (0.1, 0.2)), (1, (0.1, 0.2, 0.3, 0.4))):
            with self.subTest(p=p, parameters=parameters), self.assertRaises(ValueError):
                e4._simulate(fixture_data(3), spec, parameters, p)


class PolicyAndOptimizerNullTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.config = yaml.safe_load((root / 'configs/experiment_config_v2.yaml').read_text(encoding='utf-8-sig'))
        cls.polynomial = {(1,): -1, (2,): 0.5, (1, 2, 3): 2}
        cls.design = QAOADesign('fully_quadratized', None, _evaluate_design(
            cls.polynomial, n_original=3, actions=((1, 2),),
            selector=cls.config['selector'], apply_qaoa_hard_limits=True))
        cls.moments = e4.RelaxationMoments(-1.0, {1: 0.5, 2: 0.5, 3: 0.5},
                                         {(1, 2): 0.25, (1, 3): 0.25, (2, 3): 0.25},
                                         'optimal', 'synthetic null control', 0.0)
        cls.data = statevector_data(cls.polynomial, cls.design.evaluation.representation, optimum_original=-1)

    def test_half_original_moments_do_not_imply_half_auxiliary(self):
        specs = e4.warm_start_specs(self.design, self.moments, clipping_delta=0.05)
        self.assertEqual(specs[1].probabilities, (0.5, 0.5, 0.5, 0.5))
        self.assertEqual(specs[2].probabilities, (0.5, 0.5, 0.5, 0.25))
        self.assertEqual(specs[3].probabilities, (0.5, 0.5, 0.5, 0.25))
        cold = e4._simulate(self.data, specs[0], (), 0)
        auxiliary = e4._simulate(self.data, specs[3], (), 0)
        self.assertGreater(np.max(np.abs(np.abs(cold)**2 - np.abs(auxiliary)**2)), 0.01)

    def test_auxiliary_index_and_existing_clipping_semantics_preserved(self):
        moments = e4.RelaxationMoments(-1, {1: 0, 2: 1, 3: 0.4}, {(1, 2): 0}, 'optimal', '', 0)
        specs = e4.warm_start_specs(self.design, moments, clipping_delta=0.05)
        self.assertEqual(specs[2].probabilities, (0.05, 0.95, 0.4, 0.05))
        self.assertEqual(specs[3].probabilities, (0.05, 0.95, 0.4, 0.05 * 0.95))
        rep = self.design.evaluation.representation
        self.assertEqual(rep.auxiliary_indices[(1, 2)], 4)

    def test_same_seed_60_evaluation_optimizer_traces_match_across_all_null_policies(self):
        config = copy.deepcopy(self.config['qaoa'])
        config['optimizer']['objective_evaluations'] = 60
        specs = e4.warm_start_specs(self.design, self.moments, clipping_delta=0.05)
        null_specs = [specs[0]] + [e4.WarmStartSpec(s.policy, s.pair_closure, (0.5,) * 4) for s in specs[1:]]
        original_simulate = e4._simulate
        for p in (1, 2):
            for restart in range(3):
                reference_row = reference_trace = None
                for spec in null_specs:
                    trace = []
                    def record(data, warm_spec, parameters, depth):
                        state = original_simulate(data, warm_spec, parameters, depth)
                        trace.append((tuple(float(x) for x in parameters), float(np.abs(state)**2 @ data.original_energies)))
                        return state
                    with patch.object(e4, '_simulate', side_effect=record):
                        row = e4.optimize_warmstart_run(
                            instance_id='synthetic_null_control', family='max3sat', design=self.design,
                            budget=QAOABudgetSpec('equal_layer', f'equal_layer_p{p}', p, None, 8, 8*p),
                            data=self.data, warm_spec=spec, moments=self.moments, restart_id=restart,
                            optimizer_seed=config['optimizer']['seed_bundle'][restart],
                            circuit_seed=config['circuit_seed_bundle'][restart],
                            measurement_seed=config['measurement_seed_bundle'][restart],
                            qaoa_config=config, config_hash='synthetic', manifest_hash='synthetic',
                            e3_summary_hash='synthetic', code_commit='synthetic')
                    with self.subTest(p=p, restart=restart, policy=spec.pair_closure):
                        self.assertEqual(row['status'], 'pass')
                        self.assertEqual(row['evaluations'], 60)
                        self.assertEqual(row['mixer_convention'], e4.MIXER_CONVENTION)
                        if reference_row is None:
                            reference_row, reference_trace = row, trace
                        else:
                            self.assertEqual(trace, reference_trace)
                            for field in ('initial_parameters_sha256', 'optimized_parameters_json',
                                          'original_objective_mean', 'encoded_energy_mean', 'optimum_hit_rate',
                                          'auxiliary_inconsistency_rate', 'statevector_norm'):
                                self.assertEqual(row[field], reference_row[field], field)


if __name__ == '__main__':
    unittest.main(verbosity=2)
