"""Run on the Vast Linux host with /venv/main/bin/python. No package upgrades.

inspect; install [--remove-9b-cache]; start; stop. Install preserves old logs/config
and stops ONLY the known Qwen3.5-9B supervisor service. Downloads happen at start.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

MODEL = "Qwen/Qwen3-30B-A3B-GPTQ-Int4"
ROOT = Path("/workspace/qwen30b-prototype")
CACHE = Path("/workspace/models")
SERVICE = "qwen30b-prototype"


def run(*args, check=True, quiet=False):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not quiet:
        print(result.stdout, flush=True)
    if check:
        result.check_returncode()
    return result.stdout


def model_processes():
    return "\n".join(
        line
        for line in run("ps", "-eo", "pid,ppid,args", quiet=True).splitlines()
        if "vllm serve " in line or "VLLM::EngineCore" in line
    )


def remove_9b():
    model_dir = CACHE / "models--Qwen--Qwen3.5-9B"
    assert model_dir.resolve().parent == CACHE.resolve() and not model_dir.is_symlink()
    if not model_dir.exists():
        return
    shared = (CACHE / "blobs").resolve()
    candidates = {p.resolve() for p in model_dir.rglob("*") if p.is_symlink()}
    candidates = {p for p in candidates if p.is_relative_to(shared)}
    other_refs = {
        p.resolve()
        for folder in CACHE.glob("models--*")
        if folder != model_dir
        for p in folder.rglob("*")
        if p.is_symlink()
    }
    for path in sorted(candidates - other_refs):
        assert path.is_file() and path.is_relative_to(shared)
        print("Removing approved 9B blob", path, path.stat().st_size, flush=True)
        path.unlink()
    shutil.rmtree(model_dir)


def install(args):
    ROOT.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = ROOT / stamp
    evidence.mkdir()
    for name, cmd in {
        "gpu.txt": ["nvidia-smi"],
        "disk.txt": ["df", "-h", "/workspace"],
        "packages.txt": ["/venv/main/bin/python", "-m", "pip", "show", "vllm", "torch", "transformers"],
    }.items():
        (evidence / name).write_text(run(*cmd))
    with urllib.request.urlopen(f"https://huggingface.co/{MODEL}/raw/main/config.json") as response:
        config = json.load(response)
    assert config["architectures"] == ["Qwen3MoeForCausalLM"]
    assert config["quantization_config"]["bits"] == 4
    assert config["quantization_config"]["quant_method"] == "gptq"
    (evidence / "checkpoint-config.json").write_text(json.dumps(config, indent=2))
    with urllib.request.urlopen(f"https://huggingface.co/api/models/{MODEL}") as response:
        metadata = json.load(response)
    revision = metadata["sha"]
    (ROOT / "revision.txt").write_text(revision)
    processes = model_processes()
    (evidence / "processes.txt").write_text(processes)
    old = [line for line in processes.splitlines() if "vllm serve" in line and "Qwen/Qwen3.5-9B" in line]
    if old:
        (evidence / "previous-model-command.txt").write_text("\n".join(old))
        shutil.copy2("/etc/supervisor/conf.d/vllm.conf", evidence / "previous-vllm.conf")
        shutil.copy2("/var/log/portal/vllm.log", evidence / "previous-vllm.log")
        run("supervisorctl", "stop", "vllm", check=False)
        # Some template wrappers leave children outside supervisor's process group.
        # Signal only the observed old server and its directly observed EngineCore.
        old_pids = {int(line.split()[0]) for line in old}
        engine_pids = {
            int(line.split()[0])
            for line in processes.splitlines()
            if "VLLM::EngineCore" in line and int(line.split()[1]) in old_pids
        }
        for pid in old_pids | engine_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _ in range(20):
            if not model_processes():
                break
            time.sleep(1)
    remaining = model_processes()
    if any("VLLM::EngineCore" in line or "vllm serve " in line for line in remaining.splitlines()):
        raise RuntimeError("An inference process remains; inspect it before continuing")
    used = int(run("nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits").strip())
    if used > 1500:
        raise RuntimeError(f"GPU still has {used} MiB occupied; inspect before continuing")
    if args.remove_9b_cache:
        remove_9b()
    free = shutil.disk_usage(CACHE).free
    if free < 18_000_000_000:
        raise RuntimeError(f"Need at least 18 GB free for checkpoint and overhead; found {free}")
    launcher = ROOT / "serve.sh"
    launcher.write_text(f"""#!/bin/bash
set -euo pipefail
export PATH=/venv/main/bin:$PATH
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
mkdir -p {ROOT}/logs
exec > >(tee -a {ROOT}/logs/startup-$(date -u +%Y%m%dT%H%M%SZ).log) 2>&1
exec /venv/main/bin/python -m vllm.entrypoints.openai.api_server \\
  --model {MODEL} --revision {revision} \\
  --download-dir {CACHE} --host 127.0.0.1 --port 18000 \\
  --gpu-memory-utilization 0.85 --max-model-len {args.context} \\
  --max-num-seqs 1 --enforce-eager --dtype half \\
  --enable-auto-tool-choice --tool-call-parser hermes \\
  --default-chat-template-kwargs '{{"enable_thinking":false}}'
""")
    launcher.chmod(0o755)
    conf = Path(f"/etc/supervisor/conf.d/{SERVICE}.conf")
    conf.write_text(f"""[program:{SERVICE}]
command=/bin/bash {launcher}
directory={ROOT}
autostart=false
autorestart=false
startsecs=0
stopasgroup=true
killasgroup=true
stopwaitsecs=20
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
redirect_stderr=true
""")
    run("supervisorctl", "reread")
    run("supervisorctl", "update")
    print("Installed. Start explicitly; no automatic retries. Revision:", revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "inspect", "start", "stop", "set-context"])
    parser.add_argument("--remove-9b-cache", action="store_true")
    parser.add_argument("--context", type=int, default=4096)
    args = parser.parse_args()
    if args.action == "install":
        install(args)
    elif args.action == "set-context":
        if args.context not in {4096, 8192, 16384}:
            raise ValueError("Use a documented context size: 4096, 8192, or 16384")
        pid = run("supervisorctl", "pid", SERVICE, check=False).strip()
        if pid != "0":
            raise RuntimeError("Stop the prototype service before changing context")
        launcher = ROOT / "serve.sh"
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(launcher, ROOT / f"serve-before-{stamp}.sh")
        source, count = re.subn(
            r"--max-model-len \d+", f"--max-model-len {args.context}", launcher.read_text()
        )
        assert count == 1
        launcher.write_text(source)
    elif args.action == "inspect":
        run("nvidia-smi")
        run("supervisorctl", "status", SERVICE, check=False)
        run("curl", "--max-time", "5", "-sS", "http://127.0.0.1:18000/v1/models", check=False)
        for log in sorted((ROOT / "logs").glob("*.log")):
            print(log)
            run("tail", "-n", "35", str(log))
    else:
        run("supervisorctl", args.action, SERVICE)


if __name__ == "__main__":
    main()
