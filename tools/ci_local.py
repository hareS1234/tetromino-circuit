#!/usr/bin/env python3
"""Lint a workflow or replay its shell steps locally.

GitHub-hosted actions are skipped, composite steps are expanded, and dispatch inputs use their
defaults. A local pass is useful, but it is not a remote Actions run.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yml"          # selected by --workflow at run time
RUNTIME_ACTIONS = ("actions/checkout@", "actions/setup-python@", "actions/cache@", "actions/upload-artifact@")
EXPR_RE = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def make_targets() -> set[str]:
    text = (ROOT / "Makefile").read_text()
    return set(re.findall(r"^([a-zA-Z0-9_-]+):", text, re.M))


def evaluate(expr: str, inputs: dict) -> str:
    """Only the expression forms this workflow uses: `inputs.x` and `inputs.x == 'v' && 'a' || 'b'`."""
    expr = expr.strip()
    m = re.fullmatch(r"inputs\.([\w-]+)", expr)
    if m:
        if m.group(1) not in inputs:
            raise ValueError(f"unknown input {m.group(1)}")
        return str(inputs[m.group(1)])
    m = re.fullmatch(r"inputs\.([\w-]+)\s*==\s*'([^']*)'\s*&&\s*'([^']*)'\s*\|\|\s*'([^']*)'", expr)
    if m:
        if m.group(1) not in inputs:
            raise ValueError(f"unknown input {m.group(1)}")
        return m.group(3) if str(inputs[m.group(1)]) == m.group(2) else m.group(4)
    m = re.fullmatch(r"github\.event_name\s*==\s*'([^']*)'", expr)
    if m:
        return "true" if inputs.get("__event") == m.group(1) else "false"
    m = re.fullmatch(r"steps\.(\w+)\.outputs\.(\w+)", expr)
    if m:
        return inputs.get("__outputs", {}).get(m.group(1), {}).get(m.group(2), "")
    m = re.fullmatch(r"runner\.(os|arch)", expr)
    if m:
        return {"os": "Linux", "arch": "X64"}[m.group(1)]
    raise ValueError(f"unsupported expression: {expr}")


def substitute(text: str, inputs: dict) -> str:
    return EXPR_RE.sub(lambda m: evaluate(m.group(1), inputs), text)


def action_dir(uses: str) -> Path | None:
    if uses.startswith("./"):
        return ROOT / uses[2:]
    return None


def expand_steps(steps: list[dict], inputs: dict, prefix: str = "") -> list[dict]:
    """Flatten composite actions into the job's step list (each item: run/uses/env/name/id/if)."""
    out = []
    for st in steps:
        if "uses" in st:
            d = action_dir(st["uses"])
            if d is not None:
                action = load_yaml(d / "action.yml")
                sub_inputs = dict(inputs)
                for name, spec in (action.get("inputs") or {}).items():
                    sub_inputs[name] = (st.get("with") or {}).get(name, spec.get("default", ""))
                out += expand_steps(action["runs"]["steps"], sub_inputs, prefix=f"{d.name}/")
                continue
            out.append({**st, "_name": prefix + (st.get("name") or st["uses"]), "_inputs": inputs})
        else:
            out.append({**st, "_name": prefix + (st.get("name") or st["run"].strip().splitlines()[0][:70]), "_inputs": inputs})
    return out


def validate() -> list[str]:
    problems = []
    wf = load_yaml(WORKFLOW)
    for key in ("name", "on", "jobs"):
        if key not in wf and (key != "on" or True not in wf):
            problems.append(f"workflow lacks '{key}'")
    on = wf.get("on") or wf.get(True) or {}
    dispatch_inputs = {k: v.get("default", "") for k, v in ((on.get("workflow_dispatch") or {}).get("inputs") or {}).items()}
    targets = make_targets()
    for jname, job in wf["jobs"].items():
        if "runs-on" not in job or "steps" not in job:
            problems.append(f"job {jname} lacks runs-on/steps")
            continue
        if "timeout-minutes" not in job:
            problems.append(f"job {jname} lacks timeout-minutes")
        try:
            steps = expand_steps(job["steps"], {**dispatch_inputs, "__event": "workflow_dispatch"})
        except (OSError, KeyError, ValueError) as exc:
            problems.append(f"job {jname}: cannot expand steps: {exc}")
            continue
        for st in steps:
            if "uses" in st:
                uses = st["uses"]
                if not (uses.startswith(RUNTIME_ACTIONS) or action_dir(uses) is not None):
                    problems.append(f"job {jname}: unexpected action {uses}")
                if not re.fullmatch(r"[\w.-]+/[\w.-]+@v\d+|\./\.github/actions/[\w-]+", uses):
                    problems.append(f"job {jname}: action reference {uses} is not a major tag or local action")
            elif "run" in st:
                try:
                    text = substitute(st["run"], {**dispatch_inputs, "__event": "workflow_dispatch"})
                    for k, v in (st.get("env") or {}).items():
                        substitute(str(v), st["_inputs"])
                    if st.get("if"):
                        substitute("${{ " + str(st["if"]) + " }}", {**dispatch_inputs, "__event": "workflow_dispatch"})
                except ValueError as exc:
                    problems.append(f"job {jname} step '{st['_name']}': {exc}")
                    continue
                for m in re.finditer(r"(?:^|&&|;|\|\|)\s*make\s+([a-zA-Z0-9_-]+)", text, re.M):
                    if m.group(1) not in targets:
                        problems.append(f"job {jname}: make target '{m.group(1)}' does not exist")
                for m in re.finditer(r"python\s+(tools/[\w./-]+\.py)", text):
                    if not (ROOT / m.group(1)).is_file():
                        problems.append(f"job {jname}: script {m.group(1)} does not exist")
            else:
                problems.append(f"job {jname}: step without run/uses: {st}")
    return problems


def run_job(name: str, list_only: bool, event: str) -> int:
    wf = load_yaml(WORKFLOW)
    on = wf.get("on") or wf.get(True) or {}
    inputs = {k: v.get("default", "") for k, v in ((on.get("workflow_dispatch") or {}).get("inputs") or {}).items()}
    inputs["__event"] = event
    job = wf["jobs"][name]
    if job.get("if"):
        cond = substitute("${{ " + str(job["if"]) + " }}", inputs)
        print(f"[ci-local] job {name} condition `{job['if']}` -> {cond}")
        if cond != "true":
            print(f"[ci-local] job {name} would not run for event {event}; use --event workflow_dispatch to force")
            return 0
    steps = expand_steps(job["steps"], inputs)
    outputs: dict = {}
    ran = skipped = 0
    t_job = time.perf_counter()
    for k, st in enumerate(steps, 1):
        label = f"[ci-local] {name} step {k}/{len(steps)}: {st['_name']}"
        if "uses" in st:
            print(f"{label} — skipped ({st['uses']} needs the GitHub runtime)")
            skipped += 1
            continue
        ctx = {**st["_inputs"], "__event": event, "__outputs": outputs}
        if st.get("if") and substitute("${{ " + str(st["if"]) + " }}", ctx) != "true":
            print(f"{label} — skipped (if: {st['if']})")
            skipped += 1
            continue
        cmd = substitute(st["run"], ctx)
        if list_only:
            print(f"{label}\n    {cmd.strip()}")
            continue
        env = dict(os.environ)
        for kk, v in (st.get("env") or {}).items():
            env[kk] = substitute(str(v), ctx)
        with tempfile.NamedTemporaryFile("w+", delete=False, prefix="gh-output-") as fh:
            env["GITHUB_OUTPUT"] = fh.name
        print(f"{label}\n    $ {cmd.strip().splitlines()[0]}{' …' if len(cmd.strip().splitlines()) > 1 else ''}", flush=True)
        t0 = time.perf_counter()
        proc = subprocess.run(["bash", "-eo", "pipefail", "-c", cmd], cwd=ROOT, env=env)
        out_text = Path(env["GITHUB_OUTPUT"]).read_text()
        os.unlink(env["GITHUB_OUTPUT"])
        if st.get("id"):
            outputs[st["id"]] = dict(line.split("=", 1) for line in out_text.splitlines() if "=" in line)
        print(f"    -> exit {proc.returncode} in {time.perf_counter() - t0:.1f}s", flush=True)
        if proc.returncode != 0:
            print(f"[ci-local] job {name}: FAILED at step {k} ({ran} ok, {skipped} skipped)")
            return proc.returncode
        ran += 1
    if not list_only:
        print(f"CHECK ci_job_{name} {ran}/{ran}")
        print(f"[ci-local] job {name}: {ran} steps ran, {skipped} skipped (GitHub-runtime actions), {time.perf_counter() - t_job:.0f}s")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--job", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--event", default="push", help="github.event_name to emulate (push, pull_request, workflow_dispatch)")
    ap.add_argument("--workflow", default="ci.yml", help="workflow file under .github/workflows/ (default ci.yml)")
    args = ap.parse_args()
    global WORKFLOW
    WORKFLOW = WORKFLOWS / args.workflow
    if not WORKFLOW.is_file():
        ap.error(f"no such workflow file: {WORKFLOW}")
    if not args.validate and not args.job:
        ap.error("--validate and/or --job required")
    if args.validate:
        problems = validate()
        wf = load_yaml(WORKFLOW)
        n = len(wf["jobs"])
        label = "ci_workflow" if args.workflow == "ci.yml" else f"ci_workflow_{Path(args.workflow).stem.replace('-', '_')}"
        print(f"CHECK {label} {n - len({p.split(':')[0] for p in problems})}/{n}")
        if problems:
            print("ci-local: workflow validation FAILED")
            for p in problems:
                print("  -", p)
            return 1
        print(f"ci-local: {WORKFLOW.relative_to(ROOT)} OK ({', '.join(wf['jobs'])})")
    if args.job:
        return run_job(args.job, args.list, args.event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
