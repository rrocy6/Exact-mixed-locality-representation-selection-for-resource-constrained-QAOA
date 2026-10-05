"""Join the two extracted packages and restore byte-identical deduplicated files."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def safe(root,relative):
    p=(root/relative).resolve()
    if not p.is_relative_to(root.resolve()):raise ValueError('Unsafe relative path: '+relative)
    return p
def assemble(source,evidence,output):
    if output.exists():raise ValueError('Assembly output must be a new directory')
    output.mkdir(parents=True); count=0
    for label,root in [('source',source),('evidence',evidence)]:
        for p in sorted(root.rglob('*')):
            if not p.is_file():continue
            relative=p.relative_to(root).as_posix()
            if relative=='FILE_MANIFEST.csv':relative='package_metadata/'+label+'_FILE_MANIFEST.csv'
            target=safe(output,relative);target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if sha(target)!=sha(p):raise ValueError('Cross-package collision: '+relative)
            else:shutil.copy2(p,target);count+=1
    with (output/'DUPLICATE_FILE_MAP.csv').open(encoding='utf-8',newline='') as f:recipes=list(csv.DictReader(f))
    for recipe in recipes:
        source_path=safe(output,recipe['source_path']);target=safe(output,recipe['path'])
        if source_path.stat().st_size!=int(recipe['size_bytes']) or sha(source_path)!=recipe['sha256']:raise ValueError('Bad duplicate source: '+recipe['source_path'])
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(source_path,target)
        if sha(target)!=recipe['sha256']:raise ValueError('Restored file mismatch: '+recipe['path'])
    return {'copied_files':count,'restored_duplicates':len(recipes),'external_base_required_for_core_acceptance':False}
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(assemble(a.source,a.evidence,a.output),indent=2))
if __name__=='__main__':main()
