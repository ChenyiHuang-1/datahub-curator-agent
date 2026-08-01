# Architecture — Sherlock: The Metadata Detective

## One-liner
An autonomous agent that patrols your DataHub graph, investigates neglected data assets
like a detective — cross-referencing schemas, lineage, and real query logs — then writes
its findings BACK into DataHub so humans and other agents inherit the knowledge.

## Why this wins (judging criteria mapping)
- **Use of DataHub**: uses search, get_entities, get_lineage, get_dataset_queries (read)
  AND update_description, add_owners/propose, add_tags, save_document (write-back).
  "Strong projects contribute back to the graph" — that's our entire premise.
- **Technical execution**: end-to-end runnable demo against quickstart + seeded sample data.
- **Originality**: goes beyond the shipped "enrich" skill — evidence-based inference
  (owner inferred from query authors, purpose inferred from lineage + SQL, PII from
  schema patterns), incremental memory via investigation reports stored in the graph.
- **Real-world usefulness**: undocumented/orphaned tables are the #1 catalog pain.

## Components
1. **Patrol scanner** (`sherlock/patrol.py`) — finds "cold cases": datasets with no owner,
   no description, or no docs on any column. Uses MCP `search` with filters.
2. **Investigator** (`sherlock/investigate.py`) — for each cold case, gathers evidence:
   - schema fields (`list_schema_fields`)
   - upstream/downstream lineage (`get_lineage`)
   - real SQL queries hitting the table (`get_dataset_queries`)
   - sibling tables in same platform/domain for naming conventions
3. **Deduction engine** (`sherlock/deduce.py`) — LLM reasoning over evidence bundle:
   - table purpose + column descriptions (grounded, cites evidence)
   - inferred owner (most frequent query author / upstream owner)
   - PII suspects (name/email/phone/address patterns + value hints)
   - confidence score per deduction
4. **Scribe** (`sherlock/scribe.py`) — writes back via MCP mutation tools:
   - descriptions (update_description, append mode, marked as AI-generated w/ evidence)
   - owner proposals (propose, not direct set — governance-friendly)
   - PII tags (add_tags)
   - full "Case Report" markdown saved via save_document
5. **Memory** — each patrol reads prior case reports (search_documents) to skip
   solved cases and track graph health over time (documentation coverage %).

## Runtime
- Python 3.11+, MCP client via `mcp` python SDK (stdio to mcp-server-datahub, or HTTP).
- LLM: any OpenAI-compatible endpoint (env-configurable); demo uses a cheap model.
- CLI: `sherlock patrol --dry-run`, `sherlock investigate <urn>`, `sherlock report`.
- Runs one-shot or on a schedule (cron/GitHub Actions example included).

## Demo storyline (3-min video)
1. Show quickstart DataHub with seeded messy metadata (undocumented tables).
2. Run `sherlock patrol` — watch it find cold cases, investigate, deduce.
3. Refresh DataHub UI: descriptions appeared, owner proposal pending, PII tagged,
   Case Report visible in Documents. Coverage metric improved.
