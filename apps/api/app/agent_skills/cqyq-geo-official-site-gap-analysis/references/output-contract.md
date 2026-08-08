# Output contract

Return one JSON object with:

- `skill_contract`: exact supplied Skill name and SHA-256.
- `analysis_summary`: concise conclusion limited to the frozen scope.
- `confidence`: number from 0 to 1.
- `official_performance`: interpretation of the deterministic metrics supplied by the backend.
- `competitor_content_gaps[]`: observed themes, why they matter, exact evidence IDs, affected models/questions, and source URLs copied byte-for-byte from `observed_source_urls`.
- `recommendations[]`: priority, title, target page, required content, reason, exact evidence IDs, affected models/questions, and source URLs copied byte-for-byte from `observed_source_urls`. A proposed destination belongs in `target_page`, never in `source_urls`.
- `limitations[]`: missing pages, snippets, insufficient samples, or claims that cannot be measured.

Do not recompute or alter deterministic counts. Do not return an empty evidence list for a gap or recommendation. When no evidence-linked recommendation is justified, return empty arrays and explain why in `limitations`.
