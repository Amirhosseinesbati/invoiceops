# InvoiceOps synthetic extraction result — 2026-09-28

The fixed-seed full corpus (`10410`, reference date `2026-09-28`) was freshly generated. The visible-text/OCR DEMO collector ran inside the API image with Tesseract; predictions were saved before the offline scorer loaded private truth. No paid model or accounting-provider request was made.

| Split / group | Scenarios observed | Supported documents | Correct / predicted | Correct / expected | Precision / recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Development | 30/30 | 30 | 270/270 | 270/270 | 100.0000% |
| Held out | 70/70 | 67 | 601/603 | 601/603 | 99.6683% |
| Held-out native text | — | — | 486/486 | 486/486 | 100.0000% |
| Held-out scanned | — | — | 115/117 | 115/117 | 98.2906% |

The two held-out errors were vendor-name fields on scanned boxed-totals PDFs. Boxed totals scored 160/162; the other four held-out layouts and eight other header fields scored all expected fields. Three held-out documents were outside the supported-header slice. The 95% target was met **for supported synthetic documents with this DEMO parser**. It does not measure live-model quality or real supplier documents.

The 100-scenario collector did not produce operational observations: status, blocking finding, approval roles, and draft count are each 0 measured, so no operational accuracy is claimed. Actual triggered n8n runs are reported separately in [the evaluation protocol](../../docs/EVALUATION.md). The full local per-case JSON and generated reports are under ignored `generated/evaluation/`; this committed summary retains the reproducible aggregate evidence in a fresh clone. Its [machine-readable counterpart](synthetic_2026-09-28.json) contains exact numerators and denominators.
