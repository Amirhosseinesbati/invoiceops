"""Validate, import, and optionally publish the InvoiceOps n8n workflow pack.

Usage:
  python scripts/bootstrap_workflows.py check
  python scripts/bootstrap_workflows.py import
  python scripts/bootstrap_workflows.py import --activate-demo

The import requires a running, initialized n8n owner account, Docker Compose, and
INTERNAL_TOKEN in the process environment or an uncommitted .env file. It passes
the credential through stdin to a short-lived file inside the n8n container.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "workflows"
MANIFEST = WORKFLOWS / "manifest.json"
SECRET_PATH = "/tmp/invoiceops-header-credential.json"
WORKFLOW_PATH = "/tmp/invoiceops-workflows.json"


def read_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def read_workflows(manifest: dict) -> list[dict]:
    return [
        json.loads((WORKFLOWS / name).read_text(encoding="utf-8"))
        for name in manifest["import_order"]
    ]


def validate(manifest: dict, workflows: list[dict]) -> None:
    if manifest["n8n_version"] != "2.40.7":
        raise ValueError("Workflow pack must target the pinned n8n version 2.40.7")
    ids = {workflow["id"] for workflow in workflows}
    if len(ids) != len(workflows):
        raise ValueError("Duplicate workflow IDs")
    if {entry["id"] for entry in manifest["workflows"]} != ids:
        raise ValueError("Manifest IDs differ from workflow exports")
    credential_id = manifest["credential_setup"]["id"]
    for workflow in workflows:
        if workflow.get("active") is not False:
            raise ValueError(f"{workflow['name']} must be inactive in source control")
        names = {node["name"] for node in workflow["nodes"]}
        node_ids = {node["id"] for node in workflow["nodes"]}
        if len(names) != len(workflow["nodes"]) or len(node_ids) != len(workflow["nodes"]):
            raise ValueError(f"Duplicate node name or ID in {workflow['name']}")
        for source, outputs in workflow["connections"].items():
            if source not in names:
                raise ValueError(f"Unknown source node {source}")
            for branch in outputs["main"]:
                for edge in branch:
                    if edge["node"] not in names:
                        raise ValueError(f"Unknown target node {edge['node']}")
        for node in workflow["nodes"]:
            if node["type"] == "n8n-nodes-base.executeWorkflow":
                dependency = node["parameters"]["workflowId"]["value"]
                if dependency not in ids:
                    raise ValueError(f"Unresolved sub-workflow {dependency}")
            if "httpHeaderAuth" in node.get("credentials", {}):
                if node["credentials"]["httpHeaderAuth"]["id"] != credential_id:
                    raise ValueError(f"Unresolved header credential in {workflow['name']}")
            if node["type"] == "n8n-nodes-base.httpRequest":
                url = node["parameters"]["url"]
                is_xero = node["parameters"].get("nodeCredentialType") == "xeroOAuth2Api"
                if is_xero and url != "https://api.xero.com/api.xro/2.0/Invoices":
                    raise ValueError(f"Unexpected Xero URL in {node['name']}")
                if not is_xero and "INVOICEOPS_API_BASE_URL" not in url:
                    raise ValueError(f"Non-configured URL in {node['name']}")
                if "X-Internal-Token" in json.dumps(node["parameters"]):
                    raise ValueError(f"Secret header belongs in credential: {node['name']}")
        if workflow["name"] != "InvoiceOps | Shared Error Handler":
            if workflow["settings"].get("errorWorkflow") not in ids:
                raise ValueError(f"Missing error workflow for {workflow['name']}")


def compose_file() -> Path:
    for name in ("compose.yaml", "docker-compose.yml", "docker-compose.yaml"):
        candidate = ROOT / name
        if candidate.is_file():
            return candidate
    raise RuntimeError("No Docker Compose file found in project root")


def read_token() -> str:
    token = os.environ.get("INTERNAL_TOKEN", "").strip()
    if not token:
        path = ROOT / ".env"
        if path.is_file():
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line.startswith("INTERNAL_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if len(token) < 24:
        raise RuntimeError(
            "Set a random INTERNAL_TOKEN of at least 24 characters in .env or the environment"
        )
    return token


def docker_compose(
    compose: Path, args: list[str], *, payload: bytes | None = None, token: str = ""
) -> str:
    command = ["docker", "compose", "-f", str(compose), *args]
    result = subprocess.run(command, cwd=ROOT, input=payload, capture_output=True, check=False)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if token:
        output = output.replace(token, "[REDACTED]")
    if result.returncode:
        raise RuntimeError(f"Docker command failed ({result.returncode}): {output.strip()}")
    return output.strip()


def put_container_file(compose: Path, destination: str, payload: bytes, token: str) -> None:
    docker_compose(
        compose,
        ["exec", "-T", "n8n", "sh", "-c", f"umask 077; cat > {destination}"],
        payload=payload,
        token=token,
    )


def remove_container_file(compose: Path, destination: str) -> None:
    docker_compose(compose, ["exec", "-T", "n8n", "rm", "-f", destination])


def active_workflow_ids(compose: Path) -> set[str]:
    output = docker_compose(
        compose,
        [
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "invoiceops",
            "-d",
            "n8n",
            "-Atc",
            "SELECT id FROM workflow_entity WHERE active = true",
        ],
    )
    return set(output.splitlines())


def publish_demo(manifest: dict, workflows: list[dict]) -> None:
    compose = compose_file()
    connected_only = set(manifest.get("connected_only", []))
    active = active_workflow_ids(compose)
    for workflow in workflows:
        if workflow["name"] in connected_only or workflow["id"] in active:
            continue
        result = docker_compose(
            compose,
            ["exec", "-T", "n8n", "n8n", "publish:workflow", f"--id={workflow['id']}"],
        )
        if result.lower().startswith("an error") or "publish failed" in result.lower():
            raise RuntimeError(f"Publish failed for {workflow['name']}: {result}")
        print(f"Published {workflow['name']}", flush=True)
    docker_compose(compose, ["restart", "n8n"])
    active = active_workflow_ids(compose)
    missing = [
        workflow["name"]
        for workflow in workflows
        if workflow["name"] not in connected_only and workflow["id"] not in active
    ]
    accidental = [
        workflow["name"]
        for workflow in workflows
        if workflow["name"] in connected_only and workflow["id"] in active
    ]
    if missing or accidental:
        raise RuntimeError(
            f"Unexpected publication state: missing={missing}, connected={accidental}"
        )
    print("Demo workflows published; connected workflows remain inactive.", flush=True)


def import_pack(manifest: dict, workflows: list[dict], *, activate_demo: bool) -> None:
    compose = compose_file()
    token = read_token()
    credential = [
        {
            "id": manifest["credential_setup"]["id"],
            "name": manifest["credential_setup"]["name"],
            "type": "httpHeaderAuth",
            "data": {"name": "X-Internal-Token", "value": token},
        }
    ]
    try:
        put_container_file(compose, SECRET_PATH, json.dumps(credential).encode("utf-8"), token)
        result = docker_compose(
            compose,
            ["exec", "-T", "n8n", "n8n", "import:credentials", f"--input={SECRET_PATH}"],
            token=token,
        )
        if "Successfully imported 1 credential" not in result:
            raise RuntimeError(
                "n8n did not confirm credential import. Initialize the n8n owner account and retry. "
                + result
            )
    finally:
        try:
            remove_container_file(compose, SECRET_PATH)
        except RuntimeError:
            pass
    try:
        put_container_file(compose, WORKFLOW_PATH, json.dumps(workflows).encode("utf-8"), token)
        result = docker_compose(
            compose,
            [
                "exec",
                "-T",
                "n8n",
                "n8n",
                "import:workflow",
                f"--input={WORKFLOW_PATH}",
                "--activeState=false",
            ],
            token=token,
        )
        if "Successfully imported" not in result:
            raise RuntimeError("n8n did not confirm workflow import: " + result)
    finally:
        try:
            remove_container_file(compose, WORKFLOW_PATH)
        except RuntimeError:
            pass
    print(
        f"Imported {len(workflows)} workflows inactive with a server-side Header Auth credential."
    )
    if activate_demo:
        publish_demo(manifest, workflows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "import", "publish-demo"))
    parser.add_argument("--activate-demo", action="store_true")
    args = parser.parse_args()
    if args.activate_demo and args.action != "import":
        parser.error("--activate-demo requires import")
    manifest = read_manifest()
    workflows = read_workflows(manifest)
    validate(manifest, workflows)
    print(f"Validated {len(workflows)} workflow JSON files and their references.")
    if args.action == "import":
        import_pack(manifest, workflows, activate_demo=args.activate_demo)
    elif args.action == "publish-demo":
        publish_demo(manifest, workflows)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"InvoiceOps workflow bootstrap failed: {exc}", file=sys.stderr)
        sys.exit(1)
