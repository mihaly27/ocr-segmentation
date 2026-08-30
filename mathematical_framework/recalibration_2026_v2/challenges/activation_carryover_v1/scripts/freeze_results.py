#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from challenge_common import sha256_file, write_json

EXCLUDED={"cache","configs","_tmp_runs","logs","__pycache__"}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",required=True); a=ap.parse_args(); root=Path(a.root).resolve()
    manifest=root/"MANIFEST.sha256"
    files=[p for p in root.rglob("*") if p.is_file() and p!=manifest and not any(x in EXCLUDED for x in p.relative_to(root).parts) and p.name not in {"freeze_summary.json"}]
    lines=[f"{sha256_file(p)}  {p.relative_to(root).as_posix()}" for p in sorted(files)]
    manifest.write_text("\n".join(lines)+"\n",encoding="utf-8")
    summary={"version":"v21_challenge_freeze_v1","ok":True,"root":str(root),"file_count":len(files),"manifest":str(manifest),"manifest_sha256":sha256_file(manifest),"excluded_directory_names":sorted(EXCLUDED)}
    write_json(root/"freeze_summary.json",summary); print(json.dumps(summary,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
