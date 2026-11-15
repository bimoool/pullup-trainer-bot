"""Synthetic private files only; execute the self-contained installed guard's parser."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

GUARD = Path(__file__).resolve().parents[2] / "deploy/deploy-production-guarded-run.sh"
SECRET = "PLANTED-PRIVATE-TOKEN-user-918273-catalog-name"


@pytest.fixture
def diagnostic(tmp_path):
    source = GUARD.read_text().split("<<'COMPAT_DIAGNOSTIC_PY'", 1)[1].split("\n", 1)[1].split("\nCOMPAT_DIAGNOSTIC_PY", 1)[0]
    # Relocate fixed private roots only in this synthetic extracted parser.
    source = source.replace("/root/backups", str(tmp_path / "backups")).replace("/tmp/prod-guarded", str(tmp_path / "prod-guarded"))
    namespace = {"__name__": "synthetic_diagnostic"}
    exec(compile(source, str(GUARD), "exec"), namespace)  # noqa: S102 - trusted repository parser, synthetic files only
    foreign = set()

    def synthetic_root_stat(fd):
        st = os.fstat(fd)
        return SimpleNamespace(
            st_mode=st.st_mode, st_uid=123 if os.readlink(f"/proc/self/fd/{fd}") in foreign else 0,
            st_nlink=st.st_nlink, st_size=st.st_size,
        )

    namespace["os"] = SimpleNamespace(**{name: getattr(os, name) for name in (
        "open", "close", "read", "O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK",
    )}, fstat=synthetic_root_stat)
    work = tmp_path / "prod-guarded.Abc123"
    work.mkdir(mode=0o700)
    manifest, summary = (Path(namespace[key]) for key in ("INCIDENT_MANIFEST", "INCIDENT_SUMMARY"))
    manifest.parent.mkdir(mode=0o700)
    manifest.write_text(
        "run_id=prod-1dc9f00-20261115T184743Z-123\nmode=apply\n"
        f"target_sha={namespace['INCIDENT_SHA']}\nproject=pullup-trainer-bot\n"
        "dir=/root/pullup-trainer-bot\nfailed_at=2026-11-15T18:48:00Z phase=2\n"
    )
    summary.write_text(
        f"ERROR: verify-compatible failed (before-stop); see {work}/verify_before-stop.err and .txt\n"
        "!! PRODUCTION GUARDED apply FAILED at phase 2 (checkout " + namespace["INCIDENT_SHA"] +
        " and build app, then web — BEFORE stopping anything (production keeps running)), exit 1\n"
        f"mode            : apply   target sha: {namespace['INCIDENT_SHA']}\n"
        f"manifest        : {manifest}\nwork dir (logs) : {work}\n"
    )
    (work / "FAILED.txt").write_text(summary.read_text())
    result = {
        "mode": "verify-compatible", "verified": False,
        "counts": dict.fromkeys(namespace["COUNT_KEYS"], 3), "history_mutations": 1, "unresolved": 0,
        "errors": ["history_mutations=1", "superseded_live_copy:user_id=918273", "superseded_live_copy:user_id=817263", "missing_legacy_catalog:" + SECRET],
        "private_extra": SECRET,
    }
    output = work / "verify_before-stop.txt"
    output.write_text(SECRET + "\nRESULT-JSON " + json.dumps(result) + "\n" + SECRET)
    (work / "verify_before-stop.err").write_text("Traceback " + SECRET)
    for path in (manifest, summary, *work.iterdir()):
        path.chmod(0o600)

    def run():
        value = namespace["diagnostic"]("historical", "before-stop", "")
        encoded = json.dumps(value)
        assert SECRET not in encoded and "918273" not in encoded and "817263" not in encoded
        assert str(tmp_path) not in encoded and "Traceback" not in encoded
        assert value["scope"] == "HISTORICAL_FAILURE_NOT_RELEASE_ACCEPTANCE"
        return value

    return SimpleNamespace(run=run, namespace=namespace, work=work, manifest=manifest, summary=summary, output=output, result=result, foreign=foreign)


def test_historical_failure_aggregates_codes_without_private_payload(diagnostic):
    value = diagnostic.run()
    assert value["status"] == "VERIFIER_REPORTED_FAILURE"
    assert value["errors"] == {"HISTORY_MUTATIONS": 1, "SUPERSEDED_LIVE_COPY": 2, "MISSING_LEGACY_CATALOG": 1}
    assert value["counts"]["history_mutations"] == 1


@pytest.mark.parametrize("error", ["arbitrary:" + SECRET, "history_mutations=-1", "history_mutations=99999999999", SECRET])
def test_unknown_errors_are_never_exported(diagnostic, error):
    diagnostic.result["errors"] = [error]
    diagnostic.output.write_text("RESULT-JSON " + json.dumps(diagnostic.result))
    assert diagnostic.run()["errors"] == {"UNKNOWN_GUARD_ERROR": 1}


@pytest.mark.parametrize("mutation", ["empty", "malformed", "duplicate", "two_results", "bool", "negative", "huge", "verified", "oversized"])
def test_bad_machine_result_never_clears_failure(diagnostic, mutation):
    if mutation == "empty":
        diagnostic.output.write_text(SECRET)
    elif mutation == "malformed":
        diagnostic.output.write_text("RESULT-JSON {" + SECRET)
    elif mutation == "duplicate":
        diagnostic.output.write_text('RESULT-JSON {"mode":"verify-compatible","mode":"' + SECRET + '"}')
    elif mutation == "two_results":
        diagnostic.output.write_text(diagnostic.output.read_text() + "\nRESULT-JSON {}")
    elif mutation == "oversized":
        diagnostic.output.write_text("x" * (1024 * 1024 + 1))
    else:
        if mutation == "verified":
            diagnostic.result["verified"] = True
        else:
            diagnostic.result["counts"]["users_total"] = {"bool": True, "negative": -1, "huge": 10**12}[mutation]
        diagnostic.output.write_text("RESULT-JSON " + json.dumps(diagnostic.result))
    value = diagnostic.run()
    assert value["status"] in ("UNCLASSIFIED", "DIAG_UNAVAILABLE")
    assert "counts" not in value
    if mutation == "empty":
        assert value["errors"] == {"EXECUTION_ERROR_UNKNOWN": 1}


@pytest.mark.parametrize("mutation", ["missing", "symlink", "directory_symlink", "mode", "directory_mode", "foreign_owner", "hardlink", "fifo", "summary", "forged_path", "foreign_manifest", "phase", "run", "duplicate_manifest"])
def test_untrusted_private_evidence_is_unavailable(diagnostic, mutation, tmp_path):
    if mutation == "missing":
        diagnostic.output.unlink()
    elif mutation == "symlink":
        target = tmp_path / "private-secret"
        diagnostic.output.rename(target)
        diagnostic.output.symlink_to(target)
    elif mutation == "directory_symlink":
        target = tmp_path / "private-work"
        diagnostic.work.rename(target)
        diagnostic.work.symlink_to(target, target_is_directory=True)
    elif mutation == "mode":
        diagnostic.output.chmod(0o644)
    elif mutation == "directory_mode":
        diagnostic.work.chmod(0o777)
    elif mutation == "foreign_owner":
        diagnostic.foreign.add(str(diagnostic.output))
    elif mutation == "hardlink":
        os.link(diagnostic.output, tmp_path / "another-link")
    elif mutation == "fifo":
        diagnostic.output.unlink()
        os.mkfifo(diagnostic.output, 0o600)
    elif mutation == "summary":
        diagnostic.summary.write_text(SECRET)
    elif mutation == "forged_path":
        diagnostic.summary.write_text(diagnostic.summary.read_text().replace(str(diagnostic.work), "/tmp/" + SECRET))
    elif mutation == "foreign_manifest":
        diagnostic.manifest.write_text(diagnostic.manifest.read_text().replace(diagnostic.namespace["INCIDENT_SHA"], "f" * 40))
    elif mutation == "phase":
        diagnostic.manifest.write_text(diagnostic.manifest.read_text().replace("phase=2", "phase=4"))
    elif mutation == "run":
        diagnostic.manifest.write_text(diagnostic.manifest.read_text().replace("20261115T184743Z-123", "20261115T194743Z-123"))
    else:
        diagnostic.manifest.write_text(diagnostic.manifest.read_text() + "mode=apply\n")
    assert diagnostic.run()["status"] == "DIAG_UNAVAILABLE"


@pytest.mark.parametrize("key", [
    "backup_prestop", "writers_stopped_at", "backup", "backup_at", "backup_sha256",
    "migration_started_at", "migration_committed_at", "backfill_mode", "backfill_started_at",
    "backfill_done_at", "start_at", "rehearsal_ok_at", "deploy_ok_at",
])
def test_phase_two_manifest_rejects_actual_later_phase_markers(diagnostic, key):
    diagnostic.manifest.write_text(diagnostic.manifest.read_text() + key + "=" + SECRET + "\n")
    assert diagnostic.run()["status"] == "DIAG_UNAVAILABLE"


@pytest.mark.parametrize("shadow", ["cwd_json", "pythonpath_json", "sitecustomize"])
def test_host_sanitizer_never_imports_checkout_or_environment_code(tmp_path, shadow):
    import subprocess

    source = GUARD.read_text()
    function = source[source.index("safe_compatibility_diagnostic() {"):source.index("\nrollback_hint() {")]
    cwd, injected = tmp_path / "checkout", tmp_path / "injected"
    cwd.mkdir()
    injected.mkdir()
    marker = tmp_path / "executed-private-module"
    directory = cwd if shadow == "cwd_json" else injected
    module = "sitecustomize.py" if shadow == "sitecustomize" else "json.py"
    (directory / module).write_text(
        f"open({str(marker)!r}, 'w').write({SECRET!r})\nprint({SECRET!r})\n"
    )
    proc = subprocess.run(
        ["bash", "-c", "exec 7>&1\n" + function + "\nsafe_compatibility_diagnostic historical"],
        cwd=cwd, env={**os.environ, "PYTHONPATH": str(injected)},
        capture_output=True, text=True, check=False, timeout=15,
    )
    assert SECRET not in proc.stdout + proc.stderr
    assert not marker.exists(), "host sanitizer executed an injected Python module"
    assert proc.returncode == 0 and "COMPAT-DIAG " in proc.stdout
