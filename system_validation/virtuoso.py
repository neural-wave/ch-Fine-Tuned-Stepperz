"""Prepare the documented Docker deployment and retain a verifiable load receipt."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zipfile import ZipFile

from .settings import ROOT


def sources(config, *, hash_files=False):
    patients = sorted(config["patients_dir"].glob("*.ttl"))
    if not patients:
        raise ValueError(f"No top-level patient .ttl files in {config['patients_dir']}; subdirectories (including sample/) are not loaded. Select the complete dataset directory.")
    ontologies = sorted([*config["ontologies_dir"].glob("*.ttl"), *config["ontologies_dir"].glob("*.zip")])
    if not ontologies:
        raise ValueError("No ontology/terminology TTL or ZIP files; populate ontologies/ as required by its README")
    def inventory(paths):
        rows = []
        for path in paths:
            stat = path.stat()
            row = {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            if hash_files:
                with path.open("rb") as stream:
                    row["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
            rows.append(row)
        return rows
    return {"patients": inventory(patients), "ontologies": inventory(ontologies),
            "ontology_cache": inventory(sorted(config["ontology_cache_dir"].glob("*.ttl")))}


def sql_number(config, statement):
    escaped = statement.replace("%", "%25").replace("+", "%2B")
    result = subprocess.run(["docker", "exec", config["container_name"], "isql", "1111", "dba",
        os.getenv("DBA_PASSWORD", "dba"), "exec=" + escaped], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    output = result.stdout + result.stderr
    if result.returncode or "*** Error" in output:
        raise RuntimeError("Virtuoso administrative readiness query failed; check the container and DBA credentials")
    values = re.findall(r"^\s*(\d+)\s*$", output, flags=re.MULTILINE)
    if len(values) != 1:
        raise ValueError("Could not read a scalar readiness count from isql")
    return int(values[0])


def verify_mounts(config):
    result = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", config["container_name"]],
                            check=True, capture_output=True, text=True)
    mounts = {row["Destination"]: Path(row["Source"]).resolve() for row in json.loads(result.stdout)}
    for destination, key in (("/data", "patients_dir"), ("/ontologies", "ontologies_dir"), ("/ontologies-cache", "ontology_cache_dir")):
        if mounts.get(destination) != config[key].resolve():
            raise ValueError(f"Container mount {destination} does not match {key}; no automatic database recreation is allowed")


def refresh_archives(config):
    cache = config["ontology_cache_dir"]
    cache.mkdir(parents=True, exist_ok=True)
    seen = set()
    for path in sorted(config["ontologies_dir"].glob("*.zip")):
        with ZipFile(path) as archive:
            for member in archive.infolist():
                name = PurePosixPath(member.filename).name
                if member.is_dir() or not name.endswith(".ttl"):
                    continue
                if name in seen:
                    raise ValueError(f"Duplicate ontology archive basename: {name}")
                seen.add(name)
                target = (cache / name).resolve()
                if target.parent != cache.resolve():
                    raise ValueError("Ontology cache target escapes its directory")
                with archive.open(member) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def check_database(config, clients, patient_count):
    queued = sql_number(config, "SELECT COUNT(*) FROM DB.DBA.load_list WHERE ll_file LIKE '/data/%.ttl';")
    failed = sql_number(config, "SELECT COUNT(*) FROM DB.DBA.load_list WHERE ll_state IS NULL OR ll_state <> 2 OR ll_error IS NOT NULL;")
    rule = config["rule_set"].replace("'", "''")
    registered = sql_number(config, f"SELECT COUNT(*) FROM DB.DBA.SYS_RDF_SCHEMA WHERE RS_NAME = '{rule}';")
    if queued != patient_count or failed or not registered:
        raise ValueError(f"Incomplete load: queued={queued}, expected={patient_count}, failed/pending={failed}, rule_sets={registered}")
    prefix = json.dumps(config["graph_prefix"])
    graphs, _ = clients.query("SELECT ?g (COUNT(*) AS ?triples) WHERE { GRAPH ?g { ?s ?p ?o } "
                              f"FILTER(STRSTARTS(STR(?g), {prefix})) }} GROUP BY ?g")
    inventory = {row["g"]["value"]: int(row["triples"]["value"]) for row in graphs["results"]["bindings"]}
    expected = {config["graph_prefix"] + path.stem for path in config["patients_dir"].glob("*.ttl")}
    if set(inventory) != expected or any(value <= 0 for value in inventory.values()):
        raise ValueError("Loaded patient graphs differ from the source files (missing, empty or stale graphs); inspect the loader and use its documented reset only if intended")
    rule_iri = config["rule_set"]
    if any(char in rule_iri for char in '<>"\r\n'):
        raise ValueError("Invalid rule_set IRI")
    ontology, _ = clients.query(f"SELECT (COUNT(*) AS ?triples) WHERE {{ GRAPH <{rule_iri}> {{ ?s ?p ?o }} }}")
    triples = int(ontology["results"]["bindings"][0]["triples"]["value"])
    if triples <= 0:
        raise ValueError("The ontology graph is empty")
    return {"patient_graphs": dict(sorted(inventory.items())), "ontology_triples": triples,
            "queued_files": queued, "loader_errors_or_pending": failed, "registered_rule_sets": registered}


def prepare(config, clients, *, reset_patients=False):
    # Deliberate provisioning command: never called implicitly by a benchmark.
    sources(config)
    address = urlsplit(config["virtuoso_url"])
    if address.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Run prepare on the Docker/Virtuoso host using its loopback endpoint")
    bash = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash"))
    if not bash or not Path(bash).is_file():
        raise ValueError("Bash is required for the existing loaders (Git Bash on Windows, or run on Linux)")
    subprocess.run(["docker", "info"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    existed = subprocess.run(["docker", "inspect", config["container_name"]], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    if existed:
        verify_mounts(config)
    refresh_archives(config)
    print("Hashing source files before loading...", flush=True)
    manifest = sources(config, hash_files=True)
    if existed and not reset_patients:
        previous = (json.loads(config["receipt_file"].read_text(encoding="utf-8"))
                    if config["receipt_file"].is_file() else {})
        identity = lambda rows: [(row["path"], row.get("sha256")) for row in rows]
        if identity(previous.get("sources", {}).get("patients", [])) != identity(manifest["patients"]):
            raise ValueError("Existing database has no matching patient-load receipt. On the mock test database, rerun prepare --reset-patients to remove stale patient triples before loading (patient graphs only).")
    environment = {**os.environ, "PATIENTS_DIR": str(config["patients_dir"]),
        "ONTOLOGIES_DIR": str(config["ontologies_dir"]), "ONTOLOGY_CACHE_DIR": str(config["ontology_cache_dir"]),
        "CONTAINER_NAME": config["container_name"], "GRAPH_URI_PREFIX": config["graph_prefix"],
        "RULE_SET_URI": config["rule_set"], "HTTP_HOST_PORT": str(address.port or 8890)}
    scripts = ROOT / "infra/virtuoso/scripts"
    for script in scripts.glob("*.sh"):
        script.chmod(script.stat().st_mode | 0o111)
    config["receipt_file"].parent.mkdir(parents=True, exist_ok=True)
    config["receipt_file"].unlink(missing_ok=True)
    log = config["receipt_file"].with_suffix(".log")
    with log.open("w", encoding="utf-8") as stream:
        log.chmod(0o600)
        steps = [("start.sh", [])]
        # start.sh loads every ontology on a fresh database. An existing graph
        # may omit newly added files, so explicitly reload it in that case.
        if existed:
            steps.append(("load-ontologies.sh", ["--force"]))
        steps.append(("load-patients.sh", ["--reset"] if reset_patients else []))
        for script, arguments in steps:
            print(f"Preparing Virtuoso: {script} {' '.join(arguments)}; log: {log}", flush=True)
            result = subprocess.run([bash, str(scripts / script), *arguments], cwd=ROOT,
                                     env=environment, stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f"{script} failed; inspect {log}")
            if script == "start.sh":
                verify_mounts(config)
    print("Verifying the completed load...", flush=True)
    expected = {group: [{key: value for key, value in row.items() if key != "sha256"} for row in rows]
                for group, rows in manifest.items()}
    if sources(config) != expected:
        raise ValueError("Source files changed while loading; no readiness receipt was written")
    database = check_database(config, clients, len(manifest["patients"]))
    receipt = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
               "container_name": config["container_name"], "rule_set": config["rule_set"],
               "graph_prefix": config["graph_prefix"], "sources": manifest, "database": database}
    config["receipt_file"].write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


def ready(config, clients):
    if not config["receipt_file"].is_file():
        raise ValueError("Missing load receipt: run python -m system_validation prepare first")
    receipt = json.loads(config["receipt_file"].read_text(encoding="utf-8"))
    for field in ("container_name", "rule_set", "graph_prefix"):
        if receipt.get(field) != config[field]:
            raise ValueError(f"Preparation receipt does not match {field}")
    current = sources(config)
    expected = {group: [{key: value for key, value in row.items() if key != "sha256"} for row in rows]
                for group, rows in receipt["sources"].items()}
    if current != expected:
        raise ValueError("Source files/cache changed since preparation; prepare the database again")
    verify_mounts(config)
    actual = check_database(config, clients, len(current["patients"]))
    if actual != receipt["database"]:
        raise ValueError("Database inventory changed since preparation")
    return receipt
