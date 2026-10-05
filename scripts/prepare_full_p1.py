"""Create a new derived P1 configuration using the original frozen library."""
import argparse
import json
from pathlib import Path
import shutil
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import multiseed_experiment as m
from scripts.multiseed_p1 import PROTOCOL

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();source=a.source.resolve();out=a.output.resolve()
    if not out.is_relative_to(m.ROOT) or out.exists():raise ValueError('New project-local output directory required')
    old,samples,candidates,_=m.load_run(source)
    out.mkdir(parents=True);shutil.copytree(source/'inputs',out/'inputs')
    for name in ('INPUT_COPY_MANIFEST.json','candidate_manifest.csv','instance_manifest.csv'):shutil.copy2(source/name,out/name)
    cfg=dict(old);cfg.pop('config_hash')
    cfg.update(status='frozen_before_full_p1',p1_protocol=PROTOCOL,
        derived_from={'run':source.relative_to(m.ROOT).as_posix(),'config_hash':old['config_hash'],
                      'candidate_manifest_sha256':m.sha256_file(source/'candidate_manifest.csv')},
        compiler_implementation_hash=m.compiler_identity(out),implementation_hash=m.implementation_hash(),
        manifest_hashes={n:m.sha256_file(out/n) for n in ('candidate_manifest.csv','instance_manifest.csv','INPUT_COPY_MANIFEST.json')})
    cfg['config_hash']=m.stable_digest(cfg)
    m.atomic_json(out/'experiment_config.json',cfg);m.atomic_json(out/'experiment_config.yaml',cfg)
    tasks=m.make_tasks(candidates,cfg['config_hash'],cfg['implementation_hash'])
    manifest=[{**{k:v for k,v in t.items() if k!='candidate'},'input_hash':t['candidate']['input_hash']} for t in tasks]
    m.write_csv(out/'task_manifest.csv',manifest,manifest[0].keys())
    m.atomic_json(out/'environment.json',m.environment_payload(out,cfg))
    m.atomic_json(out/'RUN_STATE.json',{'status':'pass','stage':'derived_p0','formal_compilation_requested':False})
    m.load_run(out)
    print(out)
if __name__=='__main__':main()
