# Metric contract

## Scope

- Use only evidence IDs in `scope_manifest.eligible_evidence_ids`.
- Use `resolved_model_keys` and `resolved_question_plan_ids` as the exact analyzed population.
- Treat supplementary public research as context only. Never add it to observed rates.

## Classification

- `brand_mentioned`: the answer mentions the configured brand. This is not a citation.
- `official_cited`: at least one persisted answer source URL resolves to the configured official host or its verified subdomain.
- `content_use_supported`: an answer claim can be linked to a supplied official-source excerpt. If no excerpt is supplied, report `not_measurable` rather than zero.
- Count each eligible answer at most once in answer-level rates even when it contains multiple official URLs.

## Comparison

- Compare competitor patterns only in answers from the same frozen scope.
- A source URL is evidence provenance, not proof that the source is editable or owned.
- Technical crawl checks are prerequisites. They are not model observation metrics.

## Priority

- `high`: a repeated same-scope content gap is supported by at least two eligible answers, or a technical blocker prevents official content from being read.
- `medium`: the gap is supported by one eligible answer or appears only for part of the selected scope.
- `low`: a bounded improvement is useful but no current evidence shows a material citation disadvantage.
