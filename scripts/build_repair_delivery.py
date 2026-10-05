"""Build a versioned manuscript copy and artifact/source mapping from audited CSVs."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'corrections/review_v2_20260920'
RUN=OUT/'final_analysis'
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(path,payload):path.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
def main():
    checked=read(OUT/'evidence/correction_verification.json')
    audit=read(RUN/'AUDIT.json')
    if checked['status']!='pass' or audit['status']!='pass':raise RuntimeError('Passing numerical verification and audit required')
    with (RUN/'classification_flips.csv').open(encoding='utf-8-sig',newline='') as f:flips=list(csv.DictReader(f))
    groups=defaultdict(lambda:[0,0])
    for r in flips:
        group=groups[(r['family'],r['topology'])]
        group[0]+=int(r['baseline_true_cells']);group[1]+=int(r['common_true_cells'])
    table=[]
    for (family,topology),(base,common) in sorted(groups.items()):
        table.append({'family':family,'topology':topology,'baseline_true_cells':base,'common_true_cells':common,'retention':common/base if base else 'N/A'})
    with (OUT/'paper_family_topology.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(table[0]));w.writeheader();w.writerows(table)
    source=ROOT/'paper/main.tex'; original=source.read_text(encoding='utf-8')
    start=original.index(r'\subsection{Multi-seed compilation robustness}')
    end=original.index(r'\subsection{Noiseless QAOA results}',start)
    section=original[start:end]
    section=re.sub(r'contained \d+ TRUE', f"contained {checked['baseline']} TRUE", section)
    section=re.sub(r'\d+ cells were TRUE for all five seeds', f"{checked['common']} cells were TRUE for all five seeds", section)
    section=section.replace('giving a pooled retention of 0.5291.',f"giving a five-seed baseline retention of {checked['retention']:.6f}.")
    section=section.replace(r'\texttt{results/multiseed\_20260918T163717Z/}.',r'\texttt{corrections/review\_v2\_20260920/final\_analysis/}; the original resources remain under \texttt{results/multiseed\_20260918T163717Z/}.')
    section+='\n'+r'''Stability denotes retention of every baseline TRUE budget cell, without
asserting equality of the entire regions.  Of the 360 settings, '''+str(checked['retention_classes']['stable'])+r''' retain
all baseline cells, '''+str(checked['retention_classes']['partial'])+r''' retain some but not all, '''+str(checked['retention_classes']['disappeared'])+r''' have no common cells,
and '''+str(checked['retention_classes']['empty_baseline'])+r''' have an empty baseline.  The seed-wise region-presence figure reports
the fraction of settings with a nonempty TRUE region, using all 360 settings
as the denominator for each seed.  Baseline selector stability fixes the
seed-1729 minimum-J candidate and measures the fraction of its feasible
complete budget tuples that remain feasible under each other seed;
reselection and fixed-candidate coverage are reported separately.
The old saved pass metadata describes declared settings.  A prespecified
small replay through the repaired formal worker records actual pass callbacks
and verifies routed phase semantics at two fixed angles; it does not retrospectively
certify every archived circuit's contents.

'''
    # Regenerate the numerical table from verified CSVs instead of preserving literals.
    a=section.index('Max--3SAT & line--12');b=section.index(r'\bottomrule',a)
    table_tex=''
    for row in table:
        family='Max--3SAT' if row['family']=='max3sat' else 'Constructed'
        topology=row['topology'].replace('12','--12')
        table_tex+=f"{family} & {topology} & {row['baseline_true_cells']} & {row['common_true_cells']} & {row['retention']:.4f}"+r'\\'+'\n'
    section=section[:a]+table_tex+section[b:]
    manuscript=OUT/'main_repaired.tex'
    manuscript.write_text(original[:start]+section+original[end:],encoding='utf-8')
    (OUT/'MULTISEED_PAPER_FRAGMENT.tex').write_text(section,encoding='utf-8')
    historical=[]; changed=[]
    with (ROOT/'FILE_MANIFEST.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            path=ROOT/row['path']
            if sha(path)!=row['sha256']:
                changed.append(row['path'])
            if row['path'].startswith(('results/','audit/','configs/','evidence/')):
                historical.append({'path':row['path'],'unchanged':sha(path)==row['sha256']})
    preservation={'historical_files_checked':len(historical),'historical_changed':[r['path'] for r in historical if not r['unchanged']], 'modified_original_files':changed,
                  'original_manuscript_sha256':sha(source),'original_manifest_sha256':sha(ROOT/'FILE_MANIFEST.csv')}
    write(OUT/'evidence/PRESERVATION_CHECK.json',preservation)
    if preservation['historical_changed']:raise RuntimeError('Historical evidence changed')
    artifacts=[RUN/name for name in ('classification_flips.csv','selector_stability.csv','seed_region_presence.csv','seed_summary.csv','pooled_seed_summary.csv','experiment_config.yaml','TASK_ID_MAPPING.csv','AUDIT.json','ANALYSIS_STATE.json')]
    artifacts+=sorted((RUN/'figures').glob('*.svg'))
    artifacts += [manuscript,OUT/'MULTISEED_PAPER_FRAGMENT.tex',OUT/'paper_family_topology.csv',OUT/'replay/REPLAY_REPORT.json',OUT/'preflight_new/P1_REPORT.json',OUT/'evidence/correction_verification.json']
    mapping={'original_run':'results/multiseed_20260918T163717Z','correction_version':'review_v2_20260920',
        'analysis_run':RUN.relative_to(ROOT).as_posix(),'original_manuscript':{'path':'paper/main.tex','sha256':sha(source)},
        'manuscript_version':'main_repaired.tex; review draft, not a Release',
        'publication_status':'BLOCKED: no final adopted manuscript version supplied; other manuscript TODO sections remain',
        'pdf_status':'BLOCKED: pdflatex/latexmk unavailable; TeX copy not compiled',
        'artifacts':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in artifacts],
        'implementation_files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted((ROOT/'scripts').glob('*multiseed*.py'))]}
    write(OUT/'PAPER_ARTIFACT_MAP.json',mapping)
    print(json.dumps(preservation,indent=2))
if __name__=='__main__':main()
