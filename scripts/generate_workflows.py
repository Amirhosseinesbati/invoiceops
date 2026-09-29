"""Generate the reviewed n8n 2.40.7 workflow exports and manifest.

The generated JSON contains no secrets or environment-specific service URL. Run this
script after changing a node so the readable exports stay in sync with the source.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "workflows"
NS = uuid.UUID("bfb0981d-ff60-4b48-9f1c-a686400bbf58")
INTERNAL_CREDENTIAL_ID = "InvoiceOpsInternal"
INTERNAL_CREDENTIAL_NAME = "InvoiceOps Internal Header"
XERO_CREDENTIAL_NAME = "InvoiceOps Xero OAuth2"
API_BASE = "$env.INVOICEOPS_API_BASE_URL"
ERROR_WORKFLOW_ID = uuid.uuid5(NS, "workflow:Shared Error Handler").hex[:16]


def stable_id(kind: str, name: str) -> str:
    return str(uuid.uuid5(NS, f"{kind}:{name}"))


def workflow_id(name: str) -> str:
    return uuid.uuid5(NS, f"workflow:{name}").hex[:16]


def node(
    name: str, node_type: str, version: float, x: int, y: int, parameters: dict, **extra: object
) -> dict:
    result = {
        "id": stable_id("node", name),
        "name": name,
        "type": f"n8n-nodes-base.{node_type}",
        "typeVersion": version,
        "position": [x, y],
        "parameters": parameters,
    }
    result.update(extra)
    return result


def internal_credential() -> dict:
    return {"httpHeaderAuth": {"id": INTERNAL_CREDENTIAL_ID, "name": INTERNAL_CREDENTIAL_NAME}}


def webhook(name: str, path: str, x: int, y: int) -> dict:
    return node(
        name,
        "webhook",
        2.1,
        x,
        y,
        {
            "httpMethod": "POST",
            "path": path,
            "authentication": "headerAuth",
            "responseMode": "responseNode",
            "options": {},
        },
        webhookId=stable_id("webhook", path),
        credentials=internal_credential(),
    )


def respond(name: str, x: int, y: int, status: int, body: str) -> dict:
    return node(
        name,
        "respondToWebhook",
        1.4,
        x,
        y,
        {"respondWith": "json", "responseBody": body, "options": {"responseCode": status}},
    )


def http(
    name: str,
    x: int,
    y: int,
    method: str,
    path: str,
    body: str | None = None,
    *,
    full_response: bool = False,
    never_error: bool = False,
    error_output: bool = False,
) -> dict:
    params: dict = {
        "method": method,
        "url": "={{ " + API_BASE + " + '" + path + "' }}",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": 30000},
    }
    if body is not None:
        params.update(
            {"sendBody": True, "contentType": "json", "specifyBody": "json", "jsonBody": body}
        )
    if full_response or never_error:
        params["options"]["response"] = {
            "response": {
                "fullResponse": full_response,
                "neverError": never_error,
                "responseFormat": "json",
            }
        }
    result = node(name, "httpRequest", 4.2, x, y, params, credentials=internal_credential())
    if error_output:
        result["onError"] = "continueErrorOutput"
    return result


def if_eq(name: str, x: int, y: int, left: str, right: str) -> dict:
    return node(
        name,
        "if",
        2.2,
        x,
        y,
        {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": stable_id("condition", name),
                        "leftValue": left,
                        "rightValue": right,
                        "operator": {"type": "string", "operation": "equals"},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    )


def if_true(name: str, x: int, y: int, left: str) -> dict:
    return node(
        name,
        "if",
        2.2,
        x,
        y,
        {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": stable_id("condition", name),
                        "leftValue": left,
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    )


def call(name: str, target: str, x: int, y: int) -> dict:
    return node(
        name,
        "executeWorkflow",
        1.2,
        x,
        y,
        {
            "source": "database",
            "workflowId": {"__rl": True, "value": workflow_id(target), "mode": "id"},
            "options": {"waitForSubWorkflow": True},
        },
    )


def trigger(name: str, x: int, y: int) -> dict:
    return node(name, "executeWorkflowTrigger", 1.1, x, y, {"inputSource": "passthrough"})


def sticky(name: str, text: str, x: int, y: int, width: int = 480) -> dict:
    return node(name, "stickyNote", 1, x, y, {"content": text, "height": 190, "width": width})


def connect(edges: list[tuple[str, str, int]]) -> dict:
    result: dict = {}
    for source, target, branch in edges:
        outputs = result.setdefault(source, {"main": []})["main"]
        while len(outputs) <= branch:
            outputs.append([])
        outputs[branch].append({"node": target, "type": "main", "index": 0})
    return result


def make_workflow(
    name: str, nodes: list[dict], edges: list[tuple[str, str, int]], *, error_workflow: bool = True
) -> dict:
    # Scheduled recovery can pass multiple items to these sub-workflows. Keep
    # references paired to the current item instead of the first item in a run.
    if name in {"Process Document", "Post Demo Draft", "Xero Draft Post"}:
        for current in nodes:
            current["parameters"] = json.loads(
                json.dumps(current["parameters"]).replace(".first().json", ".item.json")
            )
    settings = {
        "executionOrder": "v1",
        "saveDataErrorExecution": "all",
        "saveDataSuccessExecution": "all",
    }
    if error_workflow:
        settings["errorWorkflow"] = ERROR_WORKFLOW_ID
    return {
        "id": workflow_id(name),
        "name": f"InvoiceOps | {name}",
        "nodes": nodes,
        "connections": connect(edges),
        "active": False,
        "settings": settings,
        "versionId": stable_id("version", name),
        "pinData": {},
        "tags": [],
    }


def replay_intake() -> dict:
    name = "Replay Intake"
    nodes = [
        sticky(
            "Replay intake note",
            "## Local replay intake\nAuthenticated webhook. The gateway validates the event and file, persists the source, and returns an invoice ID. Acknowledge before the document job runs.",
            -800,
            -320,
        ),
        webhook("Receive Replay Event", "invoiceops-intake", -760, 0),
        http(
            "Register Intake",
            -520,
            0,
            "POST",
            "/internal/intake",
            "={{ $('Receive Replay Event').first().json.body }}",
        ),
        if_true("Already Delivered?", -280, 0, "={{ $json.duplicate }}"),
        respond(
            "Respond Duplicate",
            -40,
            -120,
            200,
            "={{ {status: 'duplicate', invoice_id: $json.invoice_id} }}",
        ),
        respond(
            "Respond Accepted",
            -40,
            140,
            202,
            "={{ {status: 'accepted', invoice_id: $json.invoice_id} }}",
        ),
        call("Process Registered Invoice", "Process Document", 200, 140),
    ]
    edges = [
        ("Receive Replay Event", "Register Intake", 0),
        ("Register Intake", "Already Delivered?", 0),
        ("Already Delivered?", "Respond Duplicate", 0),
        ("Already Delivered?", "Respond Accepted", 1),
        ("Respond Accepted", "Process Registered Invoice", 0),
    ]
    return make_workflow(name, nodes, edges)


def process_document() -> dict:
    name = "Process Document"
    nodes = [
        sticky(
            "Document processing note",
            "## Start asynchronous extraction\nThe job API persists the invoice job and returns promptly. An authenticated job-completion callback or scheduled recovery later resumes n8n; no in-memory short Wait is used.",
            -800,
            -320,
        ),
        trigger("When Invoice Registered", -760, 0),
        http(
            "Submit Extraction Job",
            -520,
            0,
            "POST",
            "/internal/jobs",
            "={{ {invoice_id: $('When Invoice Registered').first().json.invoice_id} }}",
        ),
    ]
    edges = [
        ("When Invoice Registered", "Submit Extraction Job", 0),
    ]
    return make_workflow(name, nodes, edges)


def finalize_document() -> dict:
    name = "Finalize Document"
    nodes = [
        sticky(
            "Finalize document note",
            "## Match and route completed job\nThis reusable sub-workflow receives invoice_id and job_id. Route and failure endpoints are idempotent, so a repeated callback and scheduled recovery converge on one approval/exception record. ACK is last.",
            -800,
            -320,
        ),
        trigger("When Job Completion Arrives", -760, 0),
        http(
            "Read Final Job State",
            -520,
            0,
            "GET",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '",
        ),
        if_true(
            "Job Ready for Validation?",
            -280,
            0,
            "={{ $json.status === 'completed' || $json.status === 'review' }}",
        ),
        if_eq("Job Failed?", -40, 180, "={{ $json.status }}", "failed"),
        http(
            "Record Failed Job",
            200,
            180,
            "POST",
            "/internal/invoices/"
            + "' + $('When Job Completion Arrives').item.json.invoice_id + '/processing-failed",
            "={{ {job_id: $('When Job Completion Arrives').item.json.job_id, reason: $('Read Final Job State').item.json.failure_reason || 'extraction_failed'} }}",
        ),
        http(
            "Acknowledge Failed Job",
            440,
            180,
            "POST",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '/ack",
        ),
        http(
            "Validate and Match",
            -40,
            -160,
            "POST",
            "/internal/invoices/"
            + "' + $('When Job Completion Arrives').item.json.invoice_id + '/validate",
            "={{ {job_id: $('When Job Completion Arrives').item.json.job_id} }}",
        ),
        if_eq("Stale Completion?", 200, -160, "={{ $json.status }}", "stale"),
        http(
            "Acknowledge Stale Job",
            440,
            -400,
            "POST",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '/ack",
        ),
        if_eq("Exception Route?", 440, -160, "={{ $json.route }}", "exception"),
        http(
            "Open Exception Queue",
            680,
            -260,
            "POST",
            "/internal/invoices/"
            + "' + $('When Job Completion Arrives').item.json.invoice_id + '/route",
            "={{ {route: 'exception', validation_version: $('Validate and Match').item.json.validation_version} }}",
        ),
        if_eq("Manager Route?", 680, -80, "={{ $json.route }}", "manager_and_reviewer"),
        http(
            "Request Manager and Reviewer",
            920,
            -160,
            "POST",
            "/internal/invoices/"
            + "' + $('When Job Completion Arrives').item.json.invoice_id + '/route",
            "={{ {route: 'manager_and_reviewer', validation_version: $('Validate and Match').item.json.validation_version} }}",
        ),
        http(
            "Request Reviewer",
            920,
            20,
            "POST",
            "/internal/invoices/"
            + "' + $('When Job Completion Arrives').item.json.invoice_id + '/route",
            "={{ {route: 'reviewer', validation_version: $('Validate and Match').item.json.validation_version} }}",
        ),
        http(
            "Acknowledge Exception Route",
            920,
            -300,
            "POST",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '/ack",
        ),
        http(
            "Acknowledge Manager Route",
            1160,
            -160,
            "POST",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '/ack",
        ),
        http(
            "Acknowledge Reviewer Route",
            1160,
            20,
            "POST",
            "/internal/jobs/" + "' + $('When Job Completion Arrives').item.json.job_id + '/ack",
        ),
        node("Still Running", "noOp", 1, 200, 340, {}),
    ]
    edges = [
        ("When Job Completion Arrives", "Read Final Job State", 0),
        ("Read Final Job State", "Job Ready for Validation?", 0),
        ("Job Ready for Validation?", "Validate and Match", 0),
        ("Job Ready for Validation?", "Job Failed?", 1),
        ("Job Failed?", "Record Failed Job", 0),
        ("Job Failed?", "Still Running", 1),
        ("Record Failed Job", "Acknowledge Failed Job", 0),
        ("Validate and Match", "Stale Completion?", 0),
        ("Stale Completion?", "Acknowledge Stale Job", 0),
        ("Stale Completion?", "Exception Route?", 1),
        ("Exception Route?", "Open Exception Queue", 0),
        ("Exception Route?", "Manager Route?", 1),
        ("Open Exception Queue", "Acknowledge Exception Route", 0),
        ("Manager Route?", "Request Manager and Reviewer", 0),
        ("Manager Route?", "Request Reviewer", 1),
        ("Request Manager and Reviewer", "Acknowledge Manager Route", 0),
        ("Request Reviewer", "Acknowledge Reviewer Route", 0),
    ]
    return make_workflow(name, nodes, edges)


def approval_resume() -> dict:
    name = "Approval Resume"
    nodes = [
        sticky(
            "Approval resume note",
            "## Portal decision callback\nThe portal commits an authenticated, version-bound approval first. This authenticated internal webhook only prompts n8n to claim a draft operation. The gateway rechecks all blockers atomically.",
            -800,
            -320,
        ),
        webhook("Receive Committed Decision", "invoiceops-approval", -760, 0),
        respond(
            "Acknowledge Decision",
            -520,
            0,
            202,
            "={{ {status: 'queued', invoice_id: $json.body.invoice_id} }}",
        ),
        http(
            "Claim Draft Operation",
            -280,
            0,
            "POST",
            "/internal/post/claim",
            "={{ {invoice_id: $('Receive Committed Decision').first().json.body.invoice_id} }}",
        ),
        if_true("Draft Claim Granted?", -40, 0, "={{ $json.claimed }}"),
        if_eq(
            "Use Xero Posting?",
            200,
            -120,
            "={{ $env.INVOICEOPS_ACCOUNTING_PROVIDER || 'demo' }}",
            "xero",
        ),
        call("Create Xero Draft After Approval", "Xero Draft Post", 440, -220),
        call("Create Demo Draft", "Post Demo Draft", 440, -20),
        node("No Posting Allowed", "noOp", 1, 200, 120, {}),
    ]
    edges = [
        ("Receive Committed Decision", "Acknowledge Decision", 0),
        ("Acknowledge Decision", "Claim Draft Operation", 0),
        ("Claim Draft Operation", "Draft Claim Granted?", 0),
        ("Draft Claim Granted?", "Use Xero Posting?", 0),
        ("Use Xero Posting?", "Create Xero Draft After Approval", 0),
        ("Use Xero Posting?", "Create Demo Draft", 1),
        ("Draft Claim Granted?", "No Posting Allowed", 1),
    ]
    return make_workflow(name, nodes, edges)


def resolution_resume() -> dict:
    name = "Resolution Resume"
    nodes = [
        sticky(
            "Resolution resume note",
            "## Resolved exception callback\nThe portal commits the resolution first. n8n fetches current routing policy, and the gateway rechecks the callback's validation version and all blocking findings before creating approvals.",
            -800,
            -320,
        ),
        webhook("Receive Resolved Exception", "invoiceops-resolution", -760, 0),
        respond(
            "Acknowledge Resolution",
            -520,
            0,
            202,
            "={{ {status: 'queued', invoice_id: $json.body.invoice_id} }}",
        ),
        http(
            "Read Routing State",
            -280,
            0,
            "GET",
            "/internal/invoices/"
            + "' + $('Receive Resolved Exception').first().json.body.invoice_id + '/routing-state",
        ),
        if_eq("Exception Still Required?", -40, 0, "={{ $json.route }}", "exception"),
        http(
            "Keep Exception Route",
            200,
            -200,
            "POST",
            "/internal/invoices/"
            + "' + $('Receive Resolved Exception').first().json.body.invoice_id + '/route",
            "={{ {route: 'exception', validation_version: $('Receive Resolved Exception').first().json.body.validation_version} }}",
        ),
        if_eq("Manager Review Required?", 200, 20, "={{ $json.route }}", "manager_and_reviewer"),
        http(
            "Route Resolved Manager Case",
            440,
            -60,
            "POST",
            "/internal/invoices/"
            + "' + $('Receive Resolved Exception').first().json.body.invoice_id + '/route",
            "={{ {route: 'manager_and_reviewer', validation_version: $('Receive Resolved Exception').first().json.body.validation_version} }}",
        ),
        http(
            "Route Resolved Reviewer Case",
            440,
            100,
            "POST",
            "/internal/invoices/"
            + "' + $('Receive Resolved Exception').first().json.body.invoice_id + '/route",
            "={{ {route: 'reviewer', validation_version: $('Receive Resolved Exception').first().json.body.validation_version} }}",
        ),
    ]
    edges = [
        ("Receive Resolved Exception", "Acknowledge Resolution", 0),
        ("Acknowledge Resolution", "Read Routing State", 0),
        ("Read Routing State", "Exception Still Required?", 0),
        ("Exception Still Required?", "Keep Exception Route", 0),
        ("Exception Still Required?", "Manager Review Required?", 1),
        ("Manager Review Required?", "Route Resolved Manager Case", 0),
        ("Manager Review Required?", "Route Resolved Reviewer Case", 1),
    ]
    return make_workflow(name, nodes, edges)


def job_complete_callback() -> dict:
    name = "Job Complete Callback"
    nodes = [
        sticky(
            "Job callback note",
            "## Authenticated completion callback\nThe extractor worker posts only IDs through Header Auth. n8n acknowledges promptly, then the reusable finalizer rechecks the persisted job state and routes the invoice.",
            -800,
            -320,
        ),
        webhook("Receive Job Completion", "invoiceops-job-complete", -760, 0),
        respond(
            "Acknowledge Job Callback",
            -520,
            0,
            202,
            "={{ {status: 'queued', job_id: $json.body.job_id} }}",
        ),
        node(
            "Prepare Completion IDs",
            "set",
            3.4,
            -280,
            0,
            {
                "assignments": {
                    "assignments": [
                        {
                            "id": stable_id("field", "callback-job"),
                            "name": "job_id",
                            "type": "string",
                            "value": "={{ $('Receive Job Completion').first().json.body.job_id }}",
                        },
                        {
                            "id": stable_id("field", "callback-invoice"),
                            "name": "invoice_id",
                            "type": "string",
                            "value": "={{ $('Receive Job Completion').first().json.body.invoice_id }}",
                        },
                    ]
                },
                "options": {},
            },
        ),
        call("Finalize Callback Job", "Finalize Document", -40, 0),
    ]
    edges = [
        ("Receive Job Completion", "Acknowledge Job Callback", 0),
        ("Acknowledge Job Callback", "Prepare Completion IDs", 0),
        ("Prepare Completion IDs", "Finalize Callback Job", 0),
    ]
    return make_workflow(name, nodes, edges)


def recover_job_callbacks() -> dict:
    name = "Recover Job Callbacks"
    nodes = [
        sticky(
            "Job recovery note",
            "## Recover lost callbacks\nThe gateway lists completed or failed jobs without a finalizer ACK. Each item runs the same finalizer as the callback; the durable ACK is written only after route/failure persistence.",
            -800,
            -320,
        ),
        node(
            "Every Minute",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
        ),
        http("List Unacknowledged Jobs", -520, 0, "GET", "/internal/jobs/pending-completions"),
        call("Finalize Recovered Job", "Finalize Document", -280, 0),
    ]
    edges = [
        ("Every Minute", "List Unacknowledged Jobs", 0),
        ("List Unacknowledged Jobs", "Finalize Recovered Job", 0),
    ]
    return make_workflow(name, nodes, edges)


def demo_post() -> dict:
    name = "Post Demo Draft"
    nodes = [
        sticky(
            "Draft posting note",
            "## Simulated accounting write\nA transactionally claimed operation is the only input. A timeout is uncertain; reconciliation must look up an existing bill before any resend. No payment operation exists.",
            -800,
            -320,
        ),
        trigger("When Draft Claimed", -760, 0),
        http(
            "Create Simulated Draft",
            -520,
            0,
            "POST",
            "/sim/accounting/bills",
            "={{ {operation_key: $('When Draft Claimed').first().json.operation_key, workspace_id: $('When Draft Claimed').first().json.workspace_id, vendor_id: $('When Draft Claimed').first().json.vendor_id, invoice_number: $('When Draft Claimed').first().json.invoice_number, amount: $('When Draft Claimed').first().json.amount, currency: $('When Draft Claimed').first().json.currency, bill_payload: $('When Draft Claimed').first().json.bill_payload} }}",
            full_response=True,
            never_error=True,
            error_output=True,
        ),
        if_true(
            "Draft Accepted?",
            -280,
            -80,
            "={{ $json.statusCode >= 200 && $json.statusCode < 300 && $json.body.status === 'accepted' && !!$json.body.accounting_id }}",
        ),
        http(
            "Record Draft Created",
            -40,
            -180,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id, attempt: $('When Draft Claimed').first().json.attempt, status: 'accepted', accounting_id: $('Create Simulated Draft').first().json.body.accounting_id} }}",
        ),
        http(
            "Archive Posted Demo Invoice",
            200,
            -200,
            "POST",
            "/internal/invoices/"
            + "' + $('When Draft Claimed').first().json.invoice_id + '/archive",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id} }}",
        ),
        if_true(
            "Outcome Uncertain?",
            -40,
            20,
            "={{ $json.statusCode === 408 || $json.statusCode === 429 || $json.statusCode >= 500 || $json.body.status === 'timeout' || ($json.body.status === 'accepted' && !$json.body.accounting_id) }}",
        ),
        http(
            "Record Uncertain Write",
            200,
            -20,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id, attempt: $('When Draft Claimed').first().json.attempt, status: 'uncertain', error: $('Create Simulated Draft').first().json.body?.error || 'provider_timeout'} }}",
        ),
        if_true(
            "Credential Error?",
            200,
            140,
            "={{ $json.statusCode === 401 || $json.statusCode === 403 || $json.body.status === 'credential_error' }}",
        ),
        http(
            "Record Credential Error",
            440,
            80,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id, attempt: $('When Draft Claimed').first().json.attempt, status: 'credential_error', error: $('Create Simulated Draft').first().json.body?.error || 'provider_authentication_failed'} }}",
        ),
        http(
            "Record Declined Write",
            440,
            220,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id, attempt: $('When Draft Claimed').first().json.attempt, status: 'declined', error: $('Create Simulated Draft').first().json.body?.error || 'provider_rejected'} }}",
        ),
        http(
            "Record Network Uncertainty",
            -280,
            180,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Draft Claimed').first().json.operation_id, attempt: $('When Draft Claimed').first().json.attempt, status: 'uncertain', error: $json.error?.message || 'network_timeout'} }}",
        ),
    ]
    edges = [
        ("When Draft Claimed", "Create Simulated Draft", 0),
        ("Create Simulated Draft", "Draft Accepted?", 0),
        ("Create Simulated Draft", "Record Network Uncertainty", 1),
        ("Draft Accepted?", "Record Draft Created", 0),
        ("Record Draft Created", "Archive Posted Demo Invoice", 0),
        ("Draft Accepted?", "Outcome Uncertain?", 1),
        ("Outcome Uncertain?", "Record Uncertain Write", 0),
        ("Outcome Uncertain?", "Credential Error?", 1),
        ("Credential Error?", "Record Credential Error", 0),
        ("Credential Error?", "Record Declined Write", 1),
    ]
    return make_workflow(name, nodes, edges)


def xero_post() -> dict:
    name = "Xero Draft Post"
    xero_request = node(
        "Create Xero Draft",
        "httpRequest",
        4.2,
        -520,
        0,
        {
            "method": "POST",
            "url": "https://api.xero.com/api.xro/2.0/Invoices",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "xeroOAuth2Api",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [
                    {"name": "xero-tenant-id", "value": "={{ $env.XERO_TENANT_ID }}"},
                    {
                        "name": "Idempotency-Key",
                        "value": "={{ $('When Xero Draft Claimed').first().json.operation_key }}",
                    },
                ]
            },
            "sendBody": True,
            "contentType": "json",
            "specifyBody": "json",
            "jsonBody": "={{ {Invoices: [{...$('When Xero Draft Claimed').first().json.bill_payload, Type: 'ACCPAY', Status: 'DRAFT'}]} }}",
            "options": {
                "timeout": 30000,
                "response": {
                    "response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}
                },
            },
        },
        onError="continueErrorOutput",
    )
    nodes = [
        sticky(
            "Xero posting note",
            "## Connected Xero draft\nConfigure a customer-owned Xero OAuth2 credential and tenant ID before use. Keep this workflow unpublished in DEMO. Xero idempotency keys expire after six minutes, so uncertain outcomes require GET reconciliation before retry.",
            -800,
            -320,
        ),
        trigger("When Xero Draft Claimed", -760, 0),
        xero_request,
        if_true(
            "Xero Draft Accepted?",
            -280,
            -80,
            "={{ $json.statusCode >= 200 && $json.statusCode < 300 && !!$json.body?.Invoices?.[0]?.InvoiceID }}",
        ),
        http(
            "Verify Xero Draft",
            -40,
            -180,
            "POST",
            "/internal/xero/draft-check",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, invoice: $('Create Xero Draft').first().json.body.Invoices[0]} }}",
        ),
        if_true("Xero Draft Matches Approval?", 200, -180, "={{ $json.match }}"),
        http(
            "Record Xero Draft",
            440,
            -260,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'accepted', accounting_id: $('Verify Xero Draft').first().json.accounting_id} }}",
        ),
        http(
            "Record Xero Mismatch",
            440,
            -100,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'uncertain', error: $('Verify Xero Draft').first().json.reason || 'xero_draft_mismatch'} }}",
        ),
        http(
            "Archive Posted Xero Invoice",
            680,
            -260,
            "POST",
            "/internal/invoices/"
            + "' + $('When Xero Draft Claimed').first().json.invoice_id + '/archive",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id} }}",
        ),
        if_true(
            "Xero Outcome Uncertain?",
            -40,
            20,
            "={{ $json.statusCode === 408 || $json.statusCode === 429 || $json.statusCode >= 500 || ($json.statusCode >= 200 && $json.statusCode < 300) }}",
        ),
        http(
            "Record Xero Uncertain",
            200,
            -20,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'uncertain', error: $('Create Xero Draft').first().json.body?.Message || 'xero_unknown_outcome'} }}",
        ),
        if_true(
            "Xero Credential Error?",
            200,
            140,
            "={{ $json.statusCode === 401 || $json.statusCode === 403 }}",
        ),
        http(
            "Record Xero Credential Error",
            440,
            80,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'credential_error', error: $('Create Xero Draft').first().json.body?.Message || 'xero_authentication_failed'} }}",
        ),
        http(
            "Record Xero Rejection",
            440,
            220,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'declined', error: $('Create Xero Draft').first().json.body?.Message || 'xero_rejected'} }}",
        ),
        http(
            "Record Xero Network Uncertainty",
            -280,
            180,
            "POST",
            "/internal/post/result",
            "={{ {operation_id: $('When Xero Draft Claimed').first().json.operation_id, attempt: $('When Xero Draft Claimed').first().json.attempt, status: 'uncertain', error: $json.error?.message || 'xero_network_timeout'} }}",
        ),
    ]
    edges = [
        ("When Xero Draft Claimed", "Create Xero Draft", 0),
        ("Create Xero Draft", "Xero Draft Accepted?", 0),
        ("Create Xero Draft", "Record Xero Network Uncertainty", 1),
        ("Xero Draft Accepted?", "Verify Xero Draft", 0),
        ("Verify Xero Draft", "Xero Draft Matches Approval?", 0),
        ("Xero Draft Matches Approval?", "Record Xero Draft", 0),
        ("Xero Draft Matches Approval?", "Record Xero Mismatch", 1),
        ("Record Xero Draft", "Archive Posted Xero Invoice", 0),
        ("Xero Draft Accepted?", "Xero Outcome Uncertain?", 1),
        ("Xero Outcome Uncertain?", "Record Xero Uncertain", 0),
        ("Xero Outcome Uncertain?", "Xero Credential Error?", 1),
        ("Xero Credential Error?", "Record Xero Credential Error", 0),
        ("Xero Credential Error?", "Record Xero Rejection", 1),
    ]
    return make_workflow(name, nodes, edges)


def reconciliation() -> dict:
    name = "Reconcile Drafts"
    nodes = [
        sticky(
            "Reconciliation note",
            "## Reconcile before retry\nEvery uncertain operation is looked up by its immutable operation key. The API decides whether a retry is safe after the lookup; this workflow never blindly posts another bill.",
            -800,
            -320,
        ),
        node(
            "Every Five Minutes",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}},
        ),
        if_eq(
            "Using Demo Accounting?",
            -520,
            0,
            "={{ $env.INVOICEOPS_ACCOUNTING_PROVIDER || 'demo' }}",
            "demo",
        ),
        http("List Uncertain Operations", -280, 0, "GET", "/internal/reconcile/uncertain"),
        node("Connected Reconciliation Elsewhere", "noOp", 1, -280, 180, {}),
        http(
            "Look Up Existing Draft",
            -40,
            0,
            "GET",
            "/sim/accounting/bills/by-operation/" + "' + $json.operation_key + '",
            full_response=True,
            never_error=True,
            error_output=True,
        ),
        if_true(
            "Lookup Succeeded?",
            200,
            -80,
            "={{ $json.statusCode >= 200 && $json.statusCode < 300 && typeof $json.body?.found === 'boolean' && (!$json.body.found || (typeof $json.body.accounting_id === 'string' && !!$json.body.accounting_id)) }}",
        ),
        http(
            "Record Reconciliation",
            440,
            -160,
            "POST",
            "/internal/reconcile/result",
            "={{ {operation_id: $('List Uncertain Operations').item.json.operation_id, found: $json.body.found, accounting_id: $json.body.accounting_id || null} }}",
        ),
        if_eq("Reconciled Draft Found?", 680, -160, "={{ $json.status }}", "draft_created"),
        http(
            "Archive Reconciled Invoice",
            920,
            -200,
            "POST",
            "/internal/invoices/"
            + "' + $('List Uncertain Operations').item.json.invoice_id + '/archive",
            "={{ {operation_id: $('List Uncertain Operations').item.json.operation_id} }}",
        ),
        http(
            "Record Lookup Failure",
            440,
            100,
            "POST",
            "/internal/workflow-errors",
            "={{ {workflow_id: String($workflow.id || 'unknown'), execution_id: String($execution.id || 'unknown'), stage: 'reconcile_lookup', message: ('lookup_failed_' + ($json.statusCode || $json.error?.message || 'network')).slice(0, 500)} }}",
        ),
    ]
    edges = [
        ("Every Five Minutes", "Using Demo Accounting?", 0),
        ("Using Demo Accounting?", "List Uncertain Operations", 0),
        ("Using Demo Accounting?", "Connected Reconciliation Elsewhere", 1),
        ("List Uncertain Operations", "Look Up Existing Draft", 0),
        ("Look Up Existing Draft", "Lookup Succeeded?", 0),
        ("Look Up Existing Draft", "Record Lookup Failure", 1),
        ("Lookup Succeeded?", "Record Reconciliation", 0),
        ("Record Reconciliation", "Reconciled Draft Found?", 0),
        ("Reconciled Draft Found?", "Archive Reconciled Invoice", 0),
        ("Lookup Succeeded?", "Record Lookup Failure", 1),
    ]
    return make_workflow(name, nodes, edges)


def xero_reconciliation() -> dict:
    name = "Reconcile Xero Drafts"
    classify = """const context = $('Read Xero Reconcile Context').item.json;
const response = $input.item.json;
const invoices = response.body?.Invoices;
if (response.statusCode !== 200 || !Array.isArray(invoices) ||
    Number(response.body?.pagination?.pageCount || 1) > 1) {
  return {json: {...context, lookup: 'error', reason: 'xero_lookup_incomplete'}};
}
const matches = invoices.filter(bill => bill.Type === 'ACCPAY' &&
  bill.InvoiceNumber === context.invoice_number &&
  bill.Contact?.ContactID === context.contact_id);
if (matches.length === 0 && invoices.length === 0) {
  return {json: {...context, lookup: 'absent'}};
}
if (matches.length !== 1 || invoices.length !== 1) {
  return {json: {...context, lookup: 'error', reason: 'xero_lookup_ambiguous'}};
}
return {json: {...context, lookup: 'present', invoice: matches[0]}};"""
    xero_lookup = node(
        "Look Up Xero Invoice Number",
        "httpRequest",
        4.2,
        -40,
        0,
        {
            "method": "GET",
            "url": "https://api.xero.com/api.xro/2.0/Invoices",
            "authentication": "predefinedCredentialType",
            "nodeCredentialType": "xeroOAuth2Api",
            "sendHeaders": True,
            "headerParameters": {
                "parameters": [{"name": "xero-tenant-id", "value": "={{ $env.XERO_TENANT_ID }}"}]
            },
            "sendQuery": True,
            "queryParameters": {
                "parameters": [
                    {
                        "name": "InvoiceNumbers",
                        "value": "={{ $('Read Xero Reconcile Context').item.json.invoice_number }}",
                    },
                    {
                        "name": "ContactIDs",
                        "value": "={{ $('Read Xero Reconcile Context').item.json.contact_id }}",
                    },
                ]
            },
            "options": {
                "timeout": 30000,
                "response": {
                    "response": {"fullResponse": True, "neverError": True, "responseFormat": "json"}
                },
            },
        },
        onError="continueErrorOutput",
    )
    nodes = [
        sticky(
            "Xero reconciliation note",
            "## Connected lookup before retry\nUnpublished in DEMO. Search the tenant by exact invoice number and contact, verify draft identity and amounts against the approved version, then resolve uncertainty. Ambiguous responses remain uncertain for operator investigation.",
            -800,
            -320,
        ),
        node(
            "Every Five Minutes For Xero",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}},
        ),
        if_eq(
            "Using Xero Accounting?",
            -520,
            0,
            "={{ $env.INVOICEOPS_ACCOUNTING_PROVIDER || 'demo' }}",
            "xero",
        ),
        node("Skip Xero Lookup In Demo", "noOp", 1, -280, 180, {}),
        http("List Xero Uncertain Operations", -280, 0, "GET", "/internal/reconcile/uncertain"),
        http(
            "Read Xero Reconcile Context",
            -40,
            -160,
            "GET",
            "/internal/reconcile/xero-context/" + "' + $json.operation_id + '",
        ),
        xero_lookup,
        node(
            "Classify Xero Lookup",
            "code",
            2,
            200,
            0,
            {"mode": "runOnceForEachItem", "jsCode": classify},
        ),
        if_eq("Xero Draft Found?", 440, -80, "={{ $json.lookup }}", "present"),
        if_eq("Xero Draft Absent?", 680, 100, "={{ $json.lookup }}", "absent"),
        http(
            "Verify Reconciled Xero Draft",
            680,
            -180,
            "POST",
            "/internal/xero/draft-check",
            "={{ {operation_id: $json.operation_id, attempt: $json.attempt, invoice: $json.invoice} }}",
        ),
        if_true("Xero Reconciled Fields Match?", 920, -180, "={{ $json.match }}"),
        http(
            "Record Xero Reconciliation",
            1160,
            -260,
            "POST",
            "/internal/reconcile/result",
            "={{ {operation_id: $('Read Xero Reconcile Context').item.json.operation_id, found: true, accounting_id: $json.accounting_id} }}",
        ),
        http(
            "Archive Reconciled Xero Invoice",
            1400,
            -260,
            "POST",
            "/internal/invoices/"
            + "' + $('Read Xero Reconcile Context').item.json.invoice_id + '/archive",
        ),
        http(
            "Record Absent Xero Draft",
            920,
            60,
            "POST",
            "/internal/reconcile/result",
            "={{ {operation_id: $json.operation_id, found: false} }}",
        ),
        http(
            "Flag Xero Verification Mismatch",
            1160,
            -100,
            "POST",
            "/internal/workflow-errors",
            "={{ {invoice_id: $('Read Xero Reconcile Context').item.json.invoice_id, workflow_id: String($workflow.id || 'unknown'), execution_id: String($execution.id || 'unknown'), stage: 'xero_reconcile_verify', message: 'Xero draft identity or amount differs from approved invoice'} }}",
        ),
        http(
            "Flag Ambiguous Xero Lookup",
            920,
            220,
            "POST",
            "/internal/workflow-errors",
            "={{ {invoice_id: $('Read Xero Reconcile Context').item.json.invoice_id, workflow_id: String($workflow.id || 'unknown'), execution_id: String($execution.id || 'unknown'), stage: 'xero_reconcile_lookup', message: $json.reason || 'xero_lookup_ambiguous'} }}",
        ),
        http(
            "Flag Xero Transport Failure",
            200,
            220,
            "POST",
            "/internal/workflow-errors",
            "={{ {invoice_id: $('Read Xero Reconcile Context').item.json.invoice_id, workflow_id: String($workflow.id || 'unknown'), execution_id: String($execution.id || 'unknown'), stage: 'xero_reconcile_transport', message: String($json.error?.message || $json.statusCode || 'xero_transport_failed').slice(0, 500)} }}",
        ),
    ]
    edges = [
        ("Every Five Minutes For Xero", "Using Xero Accounting?", 0),
        ("Using Xero Accounting?", "List Xero Uncertain Operations", 0),
        ("Using Xero Accounting?", "Skip Xero Lookup In Demo", 1),
        ("List Xero Uncertain Operations", "Read Xero Reconcile Context", 0),
        ("Read Xero Reconcile Context", "Look Up Xero Invoice Number", 0),
        ("Look Up Xero Invoice Number", "Classify Xero Lookup", 0),
        ("Look Up Xero Invoice Number", "Flag Xero Transport Failure", 1),
        ("Classify Xero Lookup", "Xero Draft Found?", 0),
        ("Xero Draft Found?", "Verify Reconciled Xero Draft", 0),
        ("Xero Draft Found?", "Xero Draft Absent?", 1),
        ("Verify Reconciled Xero Draft", "Xero Reconciled Fields Match?", 0),
        ("Xero Reconciled Fields Match?", "Record Xero Reconciliation", 0),
        ("Xero Reconciled Fields Match?", "Flag Xero Verification Mismatch", 1),
        ("Record Xero Reconciliation", "Archive Reconciled Xero Invoice", 0),
        ("Xero Draft Absent?", "Record Absent Xero Draft", 0),
        ("Xero Draft Absent?", "Flag Ambiguous Xero Lookup", 1),
    ]
    return make_workflow(name, nodes, edges)


def recover_approved_postings() -> dict:
    name = "Recover Approved Postings"
    nodes = [
        sticky(
            "Approved recovery note",
            "## Recover committed approvals\nThe portal callback is best effort. This schedule finds approved invoices with no posting operation and submits them through the same atomic claim gate. An existing claim is never recreated here.",
            -800,
            -320,
        ),
        node(
            "Every Two Minutes For Approvals",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 2}]}},
        ),
        http("List Pending Postings", -520, 0, "GET", "/internal/recovery/pending-postings"),
        http(
            "Claim Recovered Draft",
            -280,
            0,
            "POST",
            "/internal/post/claim",
            "={{ {invoice_id: $json.invoice_id} }}",
        ),
        if_true("Recovered Claim Granted?", -40, 0, "={{ $json.claimed }}"),
        if_eq(
            "Use Xero For Recovered Posting?",
            200,
            -100,
            "={{ $env.INVOICEOPS_ACCOUNTING_PROVIDER || 'demo' }}",
            "xero",
        ),
        call("Post Recovered Xero Draft", "Xero Draft Post", 440, -200),
        call("Post Recovered Demo Draft", "Post Demo Draft", 440, 0),
        node("Recovered Claim Blocked", "noOp", 1, 200, 100, {}),
    ]
    edges = [
        ("Every Two Minutes For Approvals", "List Pending Postings", 0),
        ("List Pending Postings", "Claim Recovered Draft", 0),
        ("Claim Recovered Draft", "Recovered Claim Granted?", 0),
        ("Recovered Claim Granted?", "Use Xero For Recovered Posting?", 0),
        ("Use Xero For Recovered Posting?", "Post Recovered Xero Draft", 0),
        ("Use Xero For Recovered Posting?", "Post Recovered Demo Draft", 1),
        ("Recovered Claim Granted?", "Recovered Claim Blocked", 1),
    ]
    return make_workflow(name, nodes, edges)


def recover_pending_routes() -> dict:
    name = "Recover Pending Routes"
    nodes = [
        sticky(
            "Route recovery note",
            "## Recover resolved exceptions\nA lost portal callback cannot strand a validated invoice. The gateway lists pending routes and rechecks the current route and validation version before creating approvals or exceptions.",
            -800,
            -320,
        ),
        node(
            "Every Two Minutes For Routes",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 2}]}},
        ),
        http("List Pending Routes", -520, 0, "GET", "/internal/recovery/pending-routes"),
        http(
            "Read Recovered Routing State",
            -280,
            0,
            "GET",
            "/internal/invoices/" + "' + $json.invoice_id + '/routing-state",
        ),
        if_eq("Recovered Exception?", -40, 0, "={{ $json.route }}", "exception"),
        http(
            "Route Recovered Exception",
            200,
            -180,
            "POST",
            "/internal/invoices/" + "' + $('List Pending Routes').item.json.invoice_id + '/route",
            "={{ {route: 'exception', validation_version: $('List Pending Routes').item.json.validation_version} }}",
        ),
        if_eq("Recovered Manager Route?", 200, 40, "={{ $json.route }}", "manager_and_reviewer"),
        http(
            "Route Recovered Manager Case",
            440,
            -40,
            "POST",
            "/internal/invoices/" + "' + $('List Pending Routes').item.json.invoice_id + '/route",
            "={{ {route: 'manager_and_reviewer', validation_version: $('List Pending Routes').item.json.validation_version} }}",
        ),
        http(
            "Route Recovered Reviewer Case",
            440,
            140,
            "POST",
            "/internal/invoices/" + "' + $('List Pending Routes').item.json.invoice_id + '/route",
            "={{ {route: 'reviewer', validation_version: $('List Pending Routes').item.json.validation_version} }}",
        ),
    ]
    edges = [
        ("Every Two Minutes For Routes", "List Pending Routes", 0),
        ("List Pending Routes", "Read Recovered Routing State", 0),
        ("Read Recovered Routing State", "Recovered Exception?", 0),
        ("Recovered Exception?", "Route Recovered Exception", 0),
        ("Recovered Exception?", "Recovered Manager Route?", 1),
        ("Recovered Manager Route?", "Route Recovered Manager Case", 0),
        ("Recovered Manager Route?", "Route Recovered Reviewer Case", 1),
    ]
    return make_workflow(name, nodes, edges)


def recover_pending_archives() -> dict:
    name = "Recover Pending Archives"
    nodes = [
        sticky(
            "Archive recovery note",
            "## Complete accepted drafts\nThe posting result is durable before archiving. This schedule retries only the idempotent archive write for draft-created invoices with no archive record.",
            -800,
            -320,
        ),
        node(
            "Every Two Minutes For Archives",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"field": "minutes", "minutesInterval": 2}]}},
        ),
        http("List Pending Archives", -520, 0, "GET", "/internal/recovery/pending-archives"),
        http(
            "Archive Recovered Draft",
            -280,
            0,
            "POST",
            "/internal/invoices/" + "' + $json.invoice_id + '/archive",
        ),
    ]
    edges = [
        ("Every Two Minutes For Archives", "List Pending Archives", 0),
        ("List Pending Archives", "Archive Recovered Draft", 0),
    ]
    return make_workflow(name, nodes, edges)


def imap_intake() -> dict:
    name = "IMAP Intake"
    encode = """const out = [];
const items = $input.all();
for (let i = 0; i < items.length; i++) {
  const item = items[i];
  const messageId = String(item.json.messageId || item.json.attributes?.uid || '').replace(/[<>]/g, '');
  if (!messageId) throw new Error('imap_message_identity_missing');
  for (const [key, meta] of Object.entries(item.binary || {})) {
    const data = await this.helpers.getBinaryDataBuffer(i, key);
    if (data.length > 8 * 1024 * 1024) throw new Error('imap_attachment_exceeds_8mb');
    const mime = data.subarray(0, 5).toString('ascii') === '%PDF-' ? 'application/pdf'
      : data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47 ? 'image/png'
      : data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff ? 'image/jpeg' : '';
    if (!mime) continue;
    const sourceId = (messageId + ':' + key).slice(0, 150);
    out.push({json: {event_id: 'imap:' + sourceId, source_system: 'imap', source_id: sourceId,
      filename: String(meta.fileName || key).slice(0, 160), mime_type: mime,
      content_base64: data.toString('base64'), received_at: item.json.date || new Date().toISOString()}});
  }
}
return out;"""
    nodes = [
        sticky(
            "IMAP intake note",
            "## Connected mailbox intake\nUnpublished until a customer-owned IMAP credential and workspace ID are configured. Each supported attachment becomes a versioned intake event. Inspect mailbox redelivery policy before publishing.",
            -800,
            -320,
        ),
        node(
            "Watch Invoice Mailbox",
            "emailReadImap",
            2.2,
            -760,
            0,
            {
                "mailbox": "INBOX",
                "postProcessAction": "nothing",
                "format": "resolved",
                "dataPropertyAttachmentsPrefixName": "attachment_",
                "options": {"trackLastMessageId": True},
            },
        ),
        node(
            "Encode Mail Attachments",
            "code",
            2,
            -520,
            0,
            {"mode": "runOnceForAllItems", "jsCode": encode},
        ),
        http(
            "Register IMAP Invoice",
            -280,
            0,
            "POST",
            "/internal/intake",
            "={{ {...$json, workspace_id: $env.INVOICEOPS_CONNECTED_WORKSPACE_ID} }}",
        ),
        if_true("IMAP Redelivery?", -40, 0, "={{ $json.duplicate }}"),
        node("Ignore IMAP Redelivery", "noOp", 1, 200, -100, {}),
        call("Process IMAP Invoice", "Process Document", 200, 100),
    ]
    edges = [
        ("Watch Invoice Mailbox", "Encode Mail Attachments", 0),
        ("Encode Mail Attachments", "Register IMAP Invoice", 0),
        ("Register IMAP Invoice", "IMAP Redelivery?", 0),
        ("IMAP Redelivery?", "Ignore IMAP Redelivery", 0),
        ("IMAP Redelivery?", "Process IMAP Invoice", 1),
    ]
    return make_workflow(name, nodes, edges)


def drive_intake() -> dict:
    name = "Google Drive Intake"
    encode = """const source = $('Watch Drive Folder').item.json;
const item = $input.item;
if (!item.binary?.data) throw new Error('drive_file_binary_missing');
const data = await this.helpers.getBinaryDataBuffer($itemIndex, 'data');
if (data.length > 8 * 1024 * 1024) throw new Error('drive_file_exceeds_8mb');
const mime = data.subarray(0, 5).toString('ascii') === '%PDF-' ? 'application/pdf'
  : data[0] === 0x89 && data[1] === 0x50 && data[2] === 0x4e && data[3] === 0x47 ? 'image/png'
  : data[0] === 0xff && data[1] === 0xd8 && data[2] === 0xff ? 'image/jpeg' : '';
if (!mime) return {json: {skip: true}};
const sourceId = String(source.id || '');
if (!sourceId) throw new Error('drive_file_identity_missing');
return {json: {event_id: 'drive:' + sourceId, source_system: 'drive', source_id: sourceId,
  filename: String(source.name || item.binary.data.fileName || 'invoice').slice(0, 160),
  mime_type: mime, content_base64: data.toString('base64'),
  received_at: source.createdTime || new Date().toISOString()}};"""
    nodes = [
        sticky(
            "Drive intake note",
            "## Connected folder intake\nUnpublished until a customer-owned Google Drive OAuth credential, folder ID, and workspace ID are configured. Watches new files in the chosen folder, downloads bytes, and reuses the durable intake gate.",
            -800,
            -320,
        ),
        node(
            "Watch Drive Folder",
            "googleDriveTrigger",
            1,
            -760,
            0,
            {
                "authentication": "oAuth2",
                "triggerOn": "specificFolder",
                "folderToWatch": {
                    "__rl": True,
                    "value": "={{ $env.GOOGLE_DRIVE_INVOICE_FOLDER_ID }}",
                    "mode": "id",
                },
                "event": "fileCreated",
                "options": {},
            },
        ),
        node(
            "Download Drive File",
            "googleDrive",
            3,
            -520,
            0,
            {
                "authentication": "oAuth2",
                "resource": "file",
                "operation": "download",
                "fileId": {
                    "__rl": True,
                    "value": "={{ $('Watch Drive Folder').item.json.id }}",
                    "mode": "id",
                },
                "options": {"binaryPropertyName": "data"},
            },
        ),
        node(
            "Encode Drive File",
            "code",
            2,
            -280,
            0,
            {"mode": "runOnceForEachItem", "jsCode": encode},
        ),
        if_true("Supported Drive File?", -40, 0, "={{ !$json.skip }}"),
        http(
            "Register Drive Invoice",
            200,
            -100,
            "POST",
            "/internal/intake",
            "={{ {...$json, workspace_id: $env.INVOICEOPS_CONNECTED_WORKSPACE_ID} }}",
        ),
        if_true("Drive Redelivery?", 440, -100, "={{ $json.duplicate }}"),
        node("Ignore Drive Redelivery", "noOp", 1, 680, -180, {}),
        call("Process Drive Invoice", "Process Document", 680, -20),
        node("Ignore Unsupported Drive File", "noOp", 1, 200, 120, {}),
    ]
    edges = [
        ("Watch Drive Folder", "Download Drive File", 0),
        ("Download Drive File", "Encode Drive File", 0),
        ("Encode Drive File", "Supported Drive File?", 0),
        ("Supported Drive File?", "Register Drive Invoice", 0),
        ("Supported Drive File?", "Ignore Unsupported Drive File", 1),
        ("Register Drive Invoice", "Drive Redelivery?", 0),
        ("Drive Redelivery?", "Ignore Drive Redelivery", 0),
        ("Drive Redelivery?", "Process Drive Invoice", 1),
    ]
    return make_workflow(name, nodes, edges)


def digest() -> dict:
    name = "Status Digest"
    nodes = [
        sticky(
            "Digest note",
            "## Stored status digest\nThe gateway computes counts from persisted business tables. A demo digest is saved in the local outbox; no real message is sent.",
            -800,
            -320,
        ),
        node(
            "Every Morning",
            "scheduleTrigger",
            1.2,
            -760,
            0,
            {"rule": {"interval": [{"triggerAtHour": 9, "triggerAtMinute": 0}]}},
        ),
        http("Build Stored Status Digest", -520, 0, "POST", "/internal/digests/run"),
    ]
    edges = [("Every Morning", "Build Stored Status Digest", 0)]
    return make_workflow(name, nodes, edges)


def error_handler() -> dict:
    name = "Shared Error Handler"
    nodes = [
        sticky(
            "Error handler note",
            "## Failure ledger\nn8n Error Trigger runs on failed triggered executions. Manual editor tests are not proof. The gateway logs the failure and execution IDs; an invoice exception requires an invoice_id correlation field.",
            -800,
            -320,
        ),
        node("On Workflow Error", "errorTrigger", 1, -760, 0, {}),
        http(
            "Record Workflow Failure",
            -520,
            0,
            "POST",
            "/internal/workflow-errors",
            "={{ {workflow_id: String($json.workflow?.id || 'unknown'), execution_id: String($json.execution?.id || 'unknown'), message: String($json.execution?.error?.message || $json.trigger?.error?.message || 'workflow_failure').slice(0, 500), stage: String($json.execution?.lastNodeExecuted || 'trigger')} }}",
        ),
    ]
    edges = [("On Workflow Error", "Record Workflow Failure", 0)]
    return make_workflow(name, nodes, edges, error_workflow=False)


WORKFLOWS = [
    ("07_shared_error.json", error_handler()),
    ("02_process_document.json", process_document()),
    ("10_finalize_document.json", finalize_document()),
    ("04_post_demo_draft.json", demo_post()),
    ("09_post_xero_draft.json", xero_post()),
    ("01_replay_intake.json", replay_intake()),
    ("11_job_complete_callback.json", job_complete_callback()),
    ("12_recover_job_callbacks.json", recover_job_callbacks()),
    ("03_approval_resume.json", approval_resume()),
    ("08_resolution_resume.json", resolution_resume()),
    ("05_reconcile_drafts.json", reconciliation()),
    ("18_reconcile_xero_drafts.json", xero_reconciliation()),
    ("13_recover_approved_postings.json", recover_approved_postings()),
    ("14_recover_pending_routes.json", recover_pending_routes()),
    ("17_recover_pending_archives.json", recover_pending_archives()),
    ("06_status_digest.json", digest()),
    ("15_imap_intake.json", imap_intake()),
    ("16_drive_intake.json", drive_intake()),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, data in WORKFLOWS:
        (OUT / filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    entries = []
    for filename, data in WORKFLOWS:
        triggers = [
            n["type"].split(".")[-1]
            for n in data["nodes"]
            if n["type"].split(".")[-1]
            in {"webhook", "scheduleTrigger", "executeWorkflowTrigger", "errorTrigger"}
        ]
        deps = sorted(
            {
                n["parameters"]["workflowId"]["value"]
                for n in data["nodes"]
                if n["type"] == "n8n-nodes-base.executeWorkflow"
            }
        )
        credential_reqs = [
            {
                "type": "httpHeaderAuth",
                "name": INTERNAL_CREDENTIAL_NAME,
                "id": INTERNAL_CREDENTIAL_ID,
            }
        ]
        if any(n["parameters"].get("nodeCredentialType") == "xeroOAuth2Api" for n in data["nodes"]):
            credential_reqs.append(
                {
                    "type": "xeroOAuth2Api",
                    "name": XERO_CREDENTIAL_NAME,
                    "setup": "connect customer Xero demo/test organisation before publishing",
                }
            )
        if any(n["type"] == "n8n-nodes-base.emailReadImap" for n in data["nodes"]):
            credential_reqs.append(
                {"type": "imap", "setup": "connect customer-owned IMAP mailbox before publishing"}
            )
        if any(
            n["type"] in {"n8n-nodes-base.googleDriveTrigger", "n8n-nodes-base.googleDrive"}
            for n in data["nodes"]
        ):
            credential_reqs.append(
                {
                    "type": "googleDriveOAuth2Api",
                    "setup": "connect customer-owned Google Drive OAuth2 credential to trigger and download nodes before publishing",
                }
            )
        entries.append(
            {
                "file": filename,
                "name": data["name"],
                "id": data["id"],
                "triggers": triggers,
                "subworkflow_ids": deps,
                "credentials": credential_reqs,
                "input": "Webhook event JSON or sub-workflow item; see node names and docs/OPERATIONS.md",
                "output": "Persisted status in gateway; no secret resume URLs",
            }
        )
    manifest = {
        "schema_version": "1.0",
        "n8n_version": "2.40.7",
        "edition": "self-hosted Community compatible; built-in nodes only",
        "import_order": [x[0] for x in WORKFLOWS],
        "credential_setup": {
            "id": INTERNAL_CREDENTIAL_ID,
            "name": INTERNAL_CREDENTIAL_NAME,
            "type": "httpHeaderAuth",
            "header_name": "X-Internal-Token",
            "value_source": "INTERNAL_TOKEN environment variable at bootstrap time",
        },
        "config": {
            "INVOICEOPS_API_BASE_URL": "internal gateway origin, e.g. http://api:8000",
            "INVOICEOPS_ACCOUNTING_PROVIDER": "demo or xero; selects posting and reconciliation branches",
            "XERO_TENANT_ID": "customer tenant header required only for connected Xero",
        },
        "connected_only": [
            "InvoiceOps | Xero Draft Post",
            "InvoiceOps | Reconcile Xero Drafts",
            "InvoiceOps | IMAP Intake",
            "InvoiceOps | Google Drive Intake",
        ],
        "workflows": entries,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
