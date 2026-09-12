"""Generate E2/E5 figures and LaTeX fragments from the verified v4 result set."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
from matplotlib.lines import Line2D
import numpy as np
from verify_resources_e5_results import verify

FAMILIES = ['cubic_spin_glass', 'max3sat']
FLABEL = ['Cubic spin glass', 'Max-3SAT']
TOPS = ['all_to_all_reference', 'device_sparse_v1', 'line_12', 'ring_12', 'heavy_hex_d3_19']
TLABEL = ['All-to-all', 'Grid (12)', 'Line (12)', 'Ring (12)', 'Heavy-hex (19)']
REPS = ['fully_quadratized', 'selective', 'matched_random_selective']
RLABEL = ['Full', 'Selective', 'Matched random']
COLORS = ['#c47742', '#198d85', '#7d68a9']


def read(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(fig, path):
    fig.savefig(path.with_suffix('.pdf'))
    fig.savefig(path.with_suffix('.png'), dpi=160)
    plt.close(fig)


def fmt(v):
    return f'{float(v):.4f}'.rstrip('0').rstrip('.')


def write_table(path, header, rows, caption):
    lines = ['% ' + caption, r'\begin{tabular}{' + 'l' * len(header) + '}', r'\hline',
             ' & '.join(header) + r' \\', r'\hline']
    lines += [' & '.join(map(str, row)) + r' \\' for row in rows]
    lines += [r'\hline', r'\end{tabular}', '']
    path.write_text('\n'.join(lines), encoding='utf-8')


def main(root):
    verify(root)
    out = root / 'paper_updates'
    out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'pdf.fonttype': 42})
    summary = read(root / 'analysis/E2_summary_vs_native.csv')
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout='constrained')
    for i, (family, flabel) in enumerate(zip(FAMILIES, FLABEL)):
        for j, (metric, label) in enumerate([('two_qubit_gates', 'Two-qubit gates'), ('two_qubit_depth', 'Two-qubit depth')]):
            ax = axes[i, j]
            for k, (rep, rlabel, color) in enumerate(zip(REPS, RLABEL, COLORS)):
                rows = [next(r for r in summary if r['family'] == family and r['topology_id'] == top and r['representation'] == rep) for top in TOPS[:2]]
                ax.bar(np.arange(2) + (k-1)*.22, [float(r[metric]) for r in rows], width=.21, label=rlabel, color=color)
            ns = [next(r['n_instances'] for r in summary if r['family'] == family and r['topology_id'] == top) for top in TOPS[:2]]
            ax.set_xticks(range(2), [TLABEL[t] + f'\ncommon n={ns[t]}' for t in range(2)])
            ax.axhline(0, color='#777', lw=.8)
            ax.grid(axis='y', alpha=.18)
            ax.set_axisbelow(True)
            ax.set_title(flabel + ' | ' + label)
            ax.set_ylabel('Median paired difference from native')
    fig.legend(*axes[0, 0].get_legend_handles_labels(), loc='outside lower center', ncol=3, frameon=False)
    fig.suptitle('E2 after selector repair | lower values indicate fewer resources', fontsize=13)
    save(fig, out / 'figure_E2_primary_v4')

    control = read(root / 'analysis/E2_selected_minus_random_summary.csv')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.7), layout='constrained')
    for ax, family, flabel in zip(axes, FAMILIES, FLABEL):
        rows = [next(r for r in control if r['family'] == family and r['topology_id'] == top) for top in TOPS]
        for offset, (metric, label, color) in zip([-.12, .12], [('two_qubit_gates', 'Gates', COLORS[0]), ('two_qubit_depth', 'Depth', COLORS[1])]):
            ax.bar(np.arange(5) + offset, [float(r[metric]) for r in rows], width=.23, label=label, color=color)
        ax.set_xticks(range(5), [TLABEL[i].replace(' ', '\n', 1) + '\nn=' + r['n_instances'] for i, r in enumerate(rows)], fontsize=8)
        ax.set_title(flabel)
        ax.set_ylabel('Median selective minus matched-random resource')
        ax.axhline(0, color='#777', lw=.8)
        ax.grid(axis='y', alpha=.18)
        ax.set_axisbelow(True)
    fig.legend(*axes[0].get_legend_handles_labels(), loc='outside lower center', ncol=2, frameon=False)
    fig.suptitle('E2 topology comparison | capacity changes the paired cohort', fontsize=13)
    save(fig, out / 'figure_E2_topologies_v4')

    endpoints = read(root / 'analysis/E5_instance_level.csv')
    rows = [r for r in endpoints if r['source_tier'] == 'compilation' and r['status'] == 'pass']
    norm_limit = max(abs(float(r['effect'])) for r in rows) or 1
    norm = TwoSlopeNorm(vmin=-norm_limit, vcenter=0, vmax=norm_limit)
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 6.5), sharex=True, sharey=True)
    metrics = [('compiled_two_qubit_gates', 'Gates'), ('compiled_two_qubit_depth', 'Depth'), ('routing_overhead', 'Routing overhead')]
    for i, topology in enumerate(TOPS[:2]):
        for j, (metric, label) in enumerate(metrics):
            ax = axes[i, j]
            group = [r for r in rows if r['topology_id'] == topology and r['metric'] == metric]
            for family, marker in zip(FAMILIES, ['o', '^']):
                part = [r for r in group if r['family'] == family]
                artist = ax.scatter([float(r['pair_reuse_score']) for r in part], [float(r['canonical_cubic_sparsity']) for r in part],
                    c=[float(r['effect']) for r in part], marker=marker, s=44, cmap='RdBu', norm=norm,
                    edgecolors='#263238', linewidths=.4)
            ax.set_title(TLABEL[i] + ': ' + label + f' (n={len(group)})', fontsize=9.5)
            ax.grid(alpha=.18)
            ax.set_axisbelow(True)
            if i == 1:
                ax.set_xlabel('Pair-reuse score')
            if j == 0:
                ax.set_ylabel('Canonical cubic sparsity')
    fig.suptitle('E5 after selector repair | fixed test instances and bins', y=.985, fontsize=13)
    handles = [Line2D([], [], marker=m, color='none', markerfacecolor='#bbb', markeredgecolor='#263238', label=l) for m, l in zip(['o', '^'], FLABEL)]
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(.5, .955), ncol=2, frameon=False)
    fig.subplots_adjust(left=.075, right=.975, top=.855, bottom=.25, hspace=.30, wspace=.12)
    cb = fig.colorbar(artist, cax=fig.add_axes((.24, .13, .52, .025)), orientation='horizontal')
    cb.set_label('Normalised control-minus-selective effect; positive favours selective', fontsize=9)
    fig.text(.5, .018, 'Colours show continuous effects. Sparse-device exclusions remain explicit; residual classifications include uncertainty.', ha='center', fontsize=8.5)
    save(fig, out / 'figure_E5_regime_v4')

    old = read(root / 'inputs/old_E5.csv')
    labels = ['help', 'little_effect', 'hurt', 'not_estimable']
    legend = ['Help', 'Residual / uncertain', 'Hurt', 'Not estimable']
    colors = ['#198d85', '#b9c4cc', '#cc704f', '#e2e5e8']
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.6), layout='constrained')
    for ax, tier, title in zip(axes, ['compilation', 'qaoa'], ['Resource endpoints', 'QAOA endpoints']):
        totals = [Counter(r['classification'] for r in group if r['source_tier'] == tier) for group in [old, endpoints]]
        bottom = np.zeros(2)
        for label, display, color in zip(labels, legend, colors):
            heights = np.array([c[label] for c in totals])
            ax.bar([0, 1], heights, bottom=bottom, color=color, label=display)
            for i, h in enumerate(heights):
                if h >= 5:
                    ax.text(i, bottom[i] + h/2, str(h), ha='center', va='center', fontsize=10)
            bottom += heights
        ticklabels = ['Before repair', 'After repair']
        if tier == 'qaoa':
            ticklabels = [label + '\nHelp=' + str(c['help']) for label, c in zip(ticklabels, totals)]
        ax.set_xticks([0, 1], ticklabels)
        ax.set_title(title + f' | n={int(bottom[0])}')
        ax.set_ylabel('Instance-endpoint count')
    fig.legend(*axes[0].get_legend_handles_labels(), loc='outside lower center', ncol=4, frameon=False, fontsize=9)
    fig.suptitle('E5 classification under the unchanged tolerance and interval rules', fontsize=12)
    save(fig, out / 'figure_E5_classification_v4')

    for top, filename in zip(TOPS[:2], ['table3_resources_v4.tex', 'table5_sparse_resources_v4.tex']):
        body = []
        for family, label in zip(FAMILIES, ['Spin glass', 'Max-3SAT']):
            for rep, rep_label in zip(REPS, RLABEL):
                r = next(r for r in summary if r['family'] == family and r['topology_id'] == top and r['representation'] == rep)
                body.append([label, rep_label, r['n_instances'], *[fmt(r[m]) for m in ['two_qubit_gates', 'two_qubit_depth', 'swap_count', 'routing_overhead']]])
        write_table(out / filename, ['Family', 'Representation', '$n$', r'$\Delta$ gates', r'$\Delta$ depth', r'$\Delta$ SWAP', r'$\Delta$ routing'], body,
                    'Common-fit paired instance medians after seed/design aggregation; differences are representation minus native.')
    capacity = read(root / 'analysis/E2_capacity_by_instance.csv')
    cap_rows = []
    for rep, label in zip(['all_native', *REPS], ['Native', *RLABEL]):
        group = [r for r in capacity if r['topology_id'] == 'device_sparse_v1' and r['representation'] == rep]
        n = sum(int(r['feasible_instances']) for r in group)
        cap_rows.append([label, f'{n}/180', f'{100*n/180:.1f}\\%'])
    write_table(out / 'table4_capacity_v4.tex', ['Representation', 'Feasible instances', 'Fraction'], cap_rows, 'Capacity is counted by unique benchmark instance.')
    diag = read(root / 'DIAGNOSTIC_COEFFICIENT_RANGES.csv')
    krows = []
    kappas = {}
    for family, label in zip(FAMILIES, ['Spin glass', 'Max-3SAT']):
        vals = [float(r['coefficient_dynamic_range_corrected']) for r in diag if r['family'] == family and r['representation'] == 'selective']
        kappas[family] = statistics.median(vals)
        krows.append([label, str(len(vals)), fmt(kappas[family])])
    write_table(out / 'table17_kappa_selective_v4.tex', ['Family', '$n$', r'Selective median $\kappa$'], krows, 'Only nonzero nonidentity collected Pauli coefficients.')
    classrows = []
    for family, label in zip(FAMILIES, ['Spin glass', 'Max-3SAT']):
        for metric in ['compiled_two_qubit_gates', 'compiled_two_qubit_depth', 'routing_overhead', 'qaoa_original_objective']:
            group = [r for r in endpoints if r['family'] == family and r['metric'] == metric]
            c = Counter(r['classification'] for r in group)
            classrows.append([label, metric.replace('_', r'\_'), *[str(c[k]) for k in labels]])
    write_table(out / 'table_E5_counts_v4.tex', ['Family', 'Metric', 'Help', 'Residual', 'Hurt', 'Not estimable'], classrows,
                'Residual includes uncertain intervals and does not establish equivalence.')
    audit = json.loads((root / 'EXECUTION_AUDIT.json').read_text(encoding='utf-8'))
    verify_record = verify(root)
    counts = audit['E5_primary_counts']
    get = lambda family, rep, metric: next(r[metric] for r in summary if r['family'] == family and r['representation'] == rep and r['topology_id'] == TOPS[0])
    paragraph = rf'''% Integrate into the CURRENT Overleaf project; this is not a complete manuscript.
\paragraph{{Resource update after the selector repair.}}
We rebuilt {audit['resource_design_groups']} changed representation/draw groups across 65 fixed
compilation-tier instances. Under the same five compiler seeds and five topology
protocols, {audit['resource_rows_processed']} scheduled rows were replaced: {verify_record['reference_compilation_rows']} deterministic
all-to-all reference compilations and {verify_record['qiskit_transpilation_rows']} Qiskit compilations passed; the remaining
{verify_record['expected_capacity_rows']} rows were expected width-capacity exclusions. There were no unexpected
compiler failures. The {verify_record['unchanged_resource_rows_verified']} unchanged resource observations retain their archived values
and source lineage. No QAOA optimization was repeated in this resource stage.

\paragraph{{Resource aggregation and updated comparisons.}}
For each design we take the median over the five transpiler seeds, then average
the five random-draw medians within an instance. Paired instance differences
are formed before their median is reported. For Max-3SAT on all-to-all,
selective-minus-native medians are ${fmt(get('max3sat','selective','two_qubit_gates'))}$ gates and
${fmt(get('max3sat','selective','two_qubit_depth'))}$ depth; the matched-random depth median is
${fmt(get('max3sat','matched_random_selective','two_qubit_depth'))}$.
These updated-design results supersede the corresponding historical-design
numbers for analyses attributed to the repaired selector.
The full four-representation grid comparison still uses the 21 common-fit
instances (nine spin-glass and twelve Max-3SAT), whereas selected-versus-random
comparisons use their own explicitly reported common-fit cohorts.
The selective nonidentity Pauli coefficient-range medians are
${fmt(kappas['cubic_spin_glass'])}$ for spin glass and ${fmt(kappas['max3sat'])}$ for Max-3SAT.

\paragraph{{Regime analysis with frozen decision rules.}}
We regenerated all {audit['E5_primary_endpoints']} primary E5 instance-endpoints using the updated
resource data and the verified selector-corrected E3 observations. The original
instance membership, coverage bins, tolerances, normalisation and paired normal
interval rules were retained. There are {counts['help']} help, {counts['little_effect']} residual little-effect,
{counts['hurt']} hurt and {counts['not_estimable']} not-estimable endpoints. The residual category includes
uncertainty: {audit['little_effect_intervals_outside_tolerance']} of its intervals extend beyond the tolerance band.
It must not be interpreted as an equivalence result. There are
{audit['E5_classification_changes']} changes of primary classification relative to the archived analysis.
The {audit['E5_additional_endpoints']} additional-topology endpoints are reported separately and are not pooled
into the primary endpoint counts. E5 keeps its frozen paired-normal rule;
E3/E6 manuscript mean intervals use the separately documented instance-level
Student-$t$ post-processing.
'''
    (out / 'PAPER_RESOURCES_E5_UPDATE_V4.tex').write_text(paragraph, encoding='utf-8')
    (out / 'README_ZH.md').write_text('本目录包含 4 张 PDF 图及 PNG、5 个 LaTeX 表片段和正文更新片段。\n\n数值来自 E2 定向重编译与 E5 重算。Table 3/4/5/17 编号对应当前 59 页审阅 PDF。新 selector 下的结果与此前冻结设计的后处理结果应明确区分。\n\nE5 主分析与附加拓扑分开报告；little_effect 包含不确定性。当前 Overleaf Source ZIP 尚未提供，本目录不是完整论文。\n', encoding='utf-8')
    print('RESOURCE/E5 PAPER MATERIALS: PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    main(a.output.resolve())
