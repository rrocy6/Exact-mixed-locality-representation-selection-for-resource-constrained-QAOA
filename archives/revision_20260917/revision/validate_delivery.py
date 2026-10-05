"""Check source integrity, references and evaluation provenance before packaging."""
from pathlib import Path
import hashlib, json, re
from collections import Counter

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT/'overleaf'
sha=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
baseline=json.loads((ROOT/'overleaf_original_hashes.json').read_text())
protected={name:digest for name,digest in baseline.items() if name.endswith('.tex') and name!='main.tex'}
assert all(sha(PROJECT/name)==digest for name,digest in protected.items()), 'A protected TeX file changed'
changed=[name for name,digest in baseline.items() if sha(PROJECT/name)!=digest]
assert changed==['main.tex'],changed
text=(PROJECT/'main.tex').read_text(encoding='utf-8')
text=re.sub(r'(?<!\\)%[^\n]*','',text)
labels=re.findall(r'\\label\{([^}]+)\}',text)
duplicates={k:v for k,v in Counter(labels).items() if v>1}
refs={k.strip() for match in re.findall(r'\\(?:[cC]ref|[eE]qref|ref)\{([^}]+)\}',text) for k in match.split(',')}
missing_refs=sorted(refs-set(labels))
citations={k.strip() for match in re.findall(r'\\cite(?:t|p)?(?:\[[^]]*\])*\{([^}]+)\}',text) for k in match.split(',')}
bib=set(re.findall(r'\\bibitem(?:\[[^]]*\])?\{([^}]+)\}',text))
missing_citations=sorted(citations-bib)
images=re.findall(r'\\includegraphics(?:\[[^]]*\])?\s*\{([^}]+)\}',text)
missing_images=[p for p in images if not any((PROJECT/prefix/p).exists() for prefix in ['', 'A_IEEE_TQE','output/pdf'])]
assert not duplicates,duplicates
assert not missing_refs,missing_refs
assert not missing_citations,missing_citations
assert not missing_images,missing_images
result=dict(protected_tex_files=sorted(protected),changed_original_files=changed,
            labels=len(labels),citations=len(citations),figures=len(images),
            missing_refs=missing_refs,missing_citations=missing_citations,missing_images=missing_images)
freeze=ROOT/'experiments/compiled_results/freeze.json'
if freeze.exists():
    f=json.loads(freeze.read_text())
    source=ROOT/'experiments/compiled_study.py'
    amended=ROOT/'experiments/compiled_results/amendment_01.json'
    if amended.exists():
        assert sha(ROOT/'experiments/compiled_study_frozen_v1.py')==f['source_sha256']
        assert sha(ROOT/'experiments/COMPILED_PROTOCOL_frozen_v1.md')==f['protocol_sha256']
        amendment=json.loads(amended.read_text())
        assert sha(source)==amendment['amended_source_sha256']
        assert sha(ROOT/'experiments/COMPILED_PROTOCOL.md')==amendment['amended_protocol_sha256']
        result['compiler_technical_amendment']=True
    else:
        assert sha(source)==f['source_sha256']
    result['compiler_instances']=len(list((ROOT/'experiments/compiled_results/instances').glob('*.json')))
    result['compiler_frozen_source_verified']=True
qfreeze=ROOT/'qaoa_new/freeze.json'
if qfreeze.exists():
    for name,digest in json.loads(qfreeze.read_text())['hashes'].items():
        assert sha(ROOT/Path(name.replace('\\','/')))==digest
    result['qaoa_instances']=len(list((ROOT/'qaoa_new/results').glob('*.json')))
    result['qaoa_frozen_source_verified']=True
(ROOT/'delivery_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))
