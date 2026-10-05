"""Read-only reviewer checks; writes results outside the submitted project."""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import sys

sys.dont_write_bytecode = True


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def normalized(row):
    return {k: "" if v is None else str(v) for k, v in row.items()}


def test_results(log):
    entries = list(re.finditer(r"^(test_\S+ \([^\n]+\)|setUpClass \([^\n]+\)) \.\.\. ", log, re.M))
    results = []
    for index, match in enumerate(entries):
        end = entries[index + 1].start() if index + 1 < len(entries) else len(log)
        block = log[match.end():end]
        status = block.splitlines()[0]
        if status not in ("ok", "ERROR", "FAIL") and not status.startswith("skipped"):
            terminal = re.search(r"^(ok|ERROR|FAIL)$", block, re.M)
            status = terminal.group(1) if terminal else "unparsed"
        results.append({"test": match.group(1), "status": status})
    return results


def test_observation(root, output_dir, session):
    log = (output_dir / "repository_tests.log").read_text()
    current = test_results(log)
    related = [r for r in current if any(module in r["test"] for module in ("test_multiseed_repairs.", "test_multiseed_experiment.", "test_p1_full_coverage."))]
    supplied = test_results((root / session["coverage_dir"] / "full_tests.log").read_text())
    missing = sorted({r["test"] for r in supplied} - {r["test"] for r in current})
    return {"summary": re.findall(r"^(?:Ran .*|FAILED .*|OK)$", log, re.M), "related_tests": len(related), "related_passed": sum(r["status"] == "ok" for r in related), "related_test_results": related, "passed": sum(r["status"] == "ok" for r in current), "errors": sum(r["status"] == "ERROR" for r in current), "skips": [r for r in current if r["status"].startswith("skipped")], "not_executed_tests_vs_supplied_log": missing, "supplied_full_test_command": read(root / session["coverage_dir"] / "full_tests.json"), "fibre_bundle_available": any((root / name).is_dir() for name in ("fibre_selector_v2", "tmp_fibre_selector_v2_full_output"))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.project.resolve()
    sys.path.insert(0, str(root))
    from scripts import multiseed_experiment as m
    from scripts.multiseed_p1 import require_full_gate

    result = {"project": str(root), "python": sys.version, "platform": platform.platform(), "checks": {}}
    for package in ("numpy", "scipy", "PyYAML", "qiskit", "qiskit-aer", "jsonschema", "psutil"):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            version = None
        result.setdefault("environment", {})[package] = version

    def check(name, function):
        try:
            result["checks"][name] = {"status": "pass", **function()}
        except Exception as exc:
            result["checks"][name] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
        print(name, result["checks"][name]["status"], flush=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    session = read(root / "P1_PACKAGING_SESSION.json")
    full = root / session["full_run"]
    cor = root / "corrections/review_v2_20260920"
    final = cor / "final_analysis"
    old = root / "results/multiseed_20260918T163717Z"

    def full_gate():
        config, samples, candidates, _ = m.load_run(full)
        require_full_gate(m, full, config, samples, candidates)
        assert m.compiler_identity(full) == config["compiler_implementation_hash"]
        return {"gate": "actual require_full_gate", "compiler_hash": config["compiler_implementation_hash"], "qiskit_recompilation_performed": False}

    check("production_full_gate", full_gate)

    def p1_raw():
        table = rows(full / "p1_repetition_rows.csv")
        files = sorted((full / "p1_attempts").glob("*.json"))
        raw = [normalized(row) for path in files for row in read(path)["rows"]]
        key = lambda r: (r["repetition"], r["task_id"])
        assert len(raw) == len(table) == 2052
        assert len({key(r) for r in raw}) == len(raw)
        assert {key(r): r for r in raw} == {key(r): r for r in table}
        workers = {(r["worker_pid"], r["worker_started_utc"]) for r in table}
        assert len(workers) == 2052
        semantic = [json.loads(r["trace_json"])["semantic"] for r in table if "semantic" in json.loads(r["trace_json"])]
        assert len(semantic) == 108
        errors = [e for s in semantic for e in s["max_errors"]]
        assert all(s["status"] == "pass" for s in semantic)
        assert all(math.isfinite(e) and 0 <= e < 1e-9 for e in errors)
        traces = [json.loads(r["trace_json"]) for r in table]
        assert all(t["observed_passes"] for t in traces)
        assert all(s == t["declared"] for t in traces for s in t["observed_sabre"])
        return {"attempt_files": len(files), "raw_csv_equal_records": len(raw), "independent_pid_started_pairs": len(workers), "semantic_rows": len(semantic), "semantic_error_values": len(errors), "maximum_semantic_error": max(errors), "observed_sabre_rows": sum(bool(t["observed_sabre"]) for t in traces)}

    check("p1_raw_observation_linkage", p1_raw)

    def resources():
        cfg, _, candidates, tasks = m.load_run(final)
        compiled = rows(final / "compilation_rows.csv")
        audit = m.validate_rows(tasks, compiled, candidates, final)
        raw = m.load_raw_rows(final, cfg)
        m.validate_rows(tasks, raw, candidates, final)
        assert {m.natural_key(r): normalized(r) for r in raw} == {m.natural_key(r): r for r in compiled}
        state = read(final / "ANALYSIS_STATE.json")
        assert state["status"] == "pass" and state["config_hash"] == cfg["config_hash"]
        for relative, digest in state["artifact_hashes"].items():
            assert sha(final / relative) == digest, relative
        digest = sha(final / "compilation_rows.csv")
        assert state["compilation_sha256"] == digest == sha(old / "compilation_rows.csv")
        return {"validation": audit, "raw_csv_equal_records": len(raw), "bound_analysis_artifacts": len(state["artifact_hashes"]), "original_compilation_unchanged": True, "compilation_sha256": digest}

    check("saved_resource_and_analysis_bindings", resources)

    def replay():
        directory = cor / "replay"
        plan = read(directory / "REPLAY_PLAN.json")
        observations = [row for p in sorted(directory.glob("attempt_*.json")) for row in read(p)["rows"]]
        original = {m.natural_key(r): r for r in rows(old / "compilation_rows.csv")}
        expected = {(cid, seed, attempt) for cid in plan["selected_candidates"] for seed, attempt in ((1729, "repeat_a"), (1729, "repeat_b"), (2718, "seed_2718"))}
        observed = set()
        errors = []
        for r in observations:
            assert r["status"] == "compiled"
            observed.add((r["candidate_id"], int(r["seed"]), r["attempt_id"]))
            trace = json.loads(r["trace_json"])
            assert trace["observed_passes"] and trace["semantic"]["status"] == "pass"
            errors.extend(trace["semantic"]["max_errors"])
            previous = json.loads(original[m.natural_key(r)]["resources_json"])
            actual = json.loads(r["resources_json"])
            assert all(abs(actual[k] - previous[k]) < 1e-12 for k in ("Q", "G", "D", "M", "J"))
        assert observed == expected and len(observations) == len(expected) == 108
        assert all(math.isfinite(e) and 0 <= e < 1e-9 for e in errors)
        old_env = read(old / "environment.json")["packages"]
        replay_env = read(directory / "environment.json")["packages"]
        assert all(old_env[p] == replay_env[p] for p in ("qiskit", "numpy", "scipy"))
        return {"rows": len(observations), "resource_mismatches": 0, "maximum_semantic_error": max(errors), "historical_environment_packages_equal": True, "new_recompilation_performed": False}

    check("saved_bounded_replay", replay)

    def index():
        paths = set()
        for entry in read(root / "EVIDENCE_INDEX.json")["entries"].values():
            for field in ("source", "tests", "logs", "artifacts"):
                paths.update(entry.get(field, []))
        missing = [p for p in sorted(paths) if not (root / p).is_file()]
        assert not missing, missing
        return {"resolved_unique_paths": len(paths)}

    check("evidence_index_paths", index)

    def paper():
        mapping = read(cor / "PAPER_ARTIFACT_MAP.json")
        mismatches = []
        items = [mapping["original_manuscript"], *mapping["artifacts"], *mapping["implementation_files"]]
        for item in items:
            actual = sha(root / item["path"])
            if actual != item["sha256"]:
                mismatches.append({"path": item["path"], "recorded": item["sha256"], "current": actual})
        return {"status": "partial" if mismatches else "pass", "checked": len(items), "mismatches": mismatches, "publication_status": mapping["publication_status"], "pdf_status": mapping["pdf_status"]}

    check("paper_map_current_source", paper)

    result["repository_test_observation"] = test_observation(root, args.output.parent, session)
    result["new_qiskit_compilations"] = 0
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
