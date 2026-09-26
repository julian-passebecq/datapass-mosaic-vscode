"""Generate content/exercise-packs/concepts-v1: concept checks (Practice language `quiz`).

Questions about what Datapass cannot execute locally: Fabric capacities, Synapse dedicated SQL
pool DWUs, Databricks compute, Unity Catalog, Delta vs Iceberg, DuckLake. Each card has a public
question (exercises.json) and a private answer with its explanation (grading.server.json); a
reference sheet in content/reference/ backs each topic. Facts checked against the vendors'
documentation on 2026-09-26.

    python scripts/authoring/gen_concepts.py
"""
import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[2] / "content" / "exercise-packs" / "concepts-v1"
REFERENCES = {
    "fabric": ("reference/fabric-capacities.md", "Fabric capacities"),
    "synapse": ("reference/synapse-dedicated-sql-pool.md", "Synapse dedicated SQL pool"),
    "databricks": ("reference/databricks-compute.md", "Databricks compute"),
    "unity": ("reference/unity-catalog.md", "Unity Catalog"),
    "formats": ("reference/table-formats.md", "Delta, Iceberg and DuckLake"),
}

# (id, topic, difficulty, title, question, choices {letter: text} or None, correct letters or accepted texts, why, hint)
CARDS = [
    ("fabric-cu-per-sku", "fabric", "easy", "Capacity units of an F SKU",
     "How many capacity units (CUs) does a Microsoft Fabric F64 capacity provide?",
     {"a": "8", "b": "32", "c": "64", "d": "128"}, ["c"],
     "The number in an F SKU is its capacity units: F2 has 2 CUs, F64 has 64 CUs, F2048 has 2048.",
     "Read the number in the SKU name."),
    ("fabric-free-viewers", "fabric", "medium", "Report viewers without a Pro licence",
     "From which F SKU can users with a Fabric free licence view Power BI content in the capacity's workspaces?",
     {"a": "F2", "b": "F16", "c": "F64", "d": "Any F SKU"}, ["c"],
     "F64 and larger include the Power BI Premium P1 viewing rights: free-licence users can read content there. Below F64, viewers still need Power BI Pro (or PPU).",
     "It is the SKU equivalent to Power BI Premium P1."),
    ("fabric-pause", "fabric", "easy", "Pausing a capacity",
     "A pay-as-you-go F capacity is paused. What stops being billed?",
     {"a": "Nothing: F capacities bill 24/7", "b": "Compute (the capacity units); OneLake storage is still billed",
      "c": "Both compute and OneLake storage", "d": "Only OneLake storage"}, ["b"],
     "Pausing stops the capacity's compute charge. OneLake storage is billed separately and continues while the capacity is paused.",
     "Storage and compute are billed separately in Fabric."),
    ("fabric-smoothing", "fabric", "medium", "Smoothing background jobs",
     "Over how long does Fabric smooth the capacity usage of a background operation (a Spark job, a pipeline run, a semantic model refresh)?",
     {"a": "5 minutes", "b": "1 hour", "c": "24 hours", "d": "7 days"}, ["c"],
     "Background operations are smoothed over 24 hours; interactive operations over at least 5 minutes. Smoothing lets a short burst run above the SKU's size and pays it back later.",
     "Background work can wait; its cost is spread over a day."),
    ("fabric-throttling-stage", "fabric", "hard", "The first throttling stage",
     "A capacity keeps running over its size. Once the smoothed future usage exceeds 10 minutes, what does Fabric do first?",
     {"a": "Rejects background jobs", "b": "Delays new interactive operations by 20 seconds",
      "c": "Rejects interactive operations", "d": "Pauses the capacity"}, ["b"],
     "Throttling has stages: over 10 minutes of future usage, interactive operations are delayed; over 60 minutes, interactive operations are rejected; over 24 hours, background jobs are rejected too.",
     "The first stage slows people down; it does not refuse them yet."),
    ("synapse-distributions", "synapse", "easy", "Distributions of a dedicated SQL pool",
     "How many distributions does every Azure Synapse dedicated SQL pool have, whatever its DWU level? (a number)",
     None, ["60"],
     "A dedicated SQL pool always spreads data over 60 distributions. Scaling the DWUs changes how many compute nodes serve those 60 distributions, not their number.",
     "It does not change when you scale."),
    ("synapse-dwu-nodes", "synapse", "medium", "Compute nodes at DW30000c",
     "At DW30000c, the largest service level, how many compute nodes serve the 60 distributions?",
     {"a": "1", "b": "10", "c": "30", "d": "60"}, ["d"],
     "DW100c to DW500c run on a single compute node holding all 60 distributions; DW30000c runs 60 compute nodes, one distribution each.",
     "At the top level, each node serves exactly one distribution."),
    ("synapse-replicate", "synapse", "medium", "Which distribution for a small dimension",
     "A 50 MB product dimension is joined by every fact query. Which table distribution avoids data movement for those joins?",
     {"a": "HASH on product_key", "b": "ROUND_ROBIN", "c": "REPLICATE", "d": "HEAP"}, ["c"],
     "A replicated table keeps a full copy on each compute node, so joins to it need no shuffle. Microsoft recommends it for tables under about 2 GB compressed. HEAP is a storage option, not a distribution.",
     "The table is small enough to copy everywhere."),
    ("synapse-cci-rows", "synapse", "hard", "Clustered columnstore and row groups",
     "A clustered columnstore index compresses best with about 1 million rows per row group. Roughly how many rows does a table need before every distribution can fill one row group?",
     {"a": "1 million", "b": "6 million", "c": "60 million", "d": "600 million"}, ["c"],
     "Each of the 60 distributions builds its own row groups, so a full row group everywhere needs about 60 x 1 million rows. Partitioning multiplies that again by the number of partitions.",
     "Multiply by the number of distributions."),
    ("synapse-pause", "synapse", "easy", "Pausing a dedicated SQL pool",
     "What does pausing a dedicated SQL pool stop billing?",
     {"a": "Compute (DWUs); storage is still billed", "b": "Storage only", "c": "Both compute and storage",
      "d": "Nothing: only deleting the pool stops billing"}, ["a"],
     "Pausing releases the compute and stops the DWU charge; the data stays and storage is still billed.",
     "Your data is kept while the pool is paused."),
    ("dbx-job-cluster", "databricks", "easy", "The cheaper compute for a nightly job",
     "A notebook job runs every night for an hour. Which classic compute is usually cheaper for it than an all-purpose cluster?",
     {"a": "A job cluster created for each run", "b": "A bigger all-purpose cluster",
      "c": "A SQL warehouse", "d": "An instance pool on its own"}, ["a"],
     "Job compute is billed at a lower DBU rate than all-purpose compute and exists only for the run. All-purpose clusters are for interactive work.",
     "Interactive compute costs more per DBU."),
    ("dbx-access-modes", "databricks", "medium", "Access modes on Unity Catalog",
     "Which access mode lets several users share one cluster while Unity Catalog enforces each user's own permissions?",
     {"a": "Dedicated (formerly single user)", "b": "Standard (formerly shared)",
      "c": "No isolation shared", "d": "Any mode, as long as the cluster autoscales"}, ["b"],
     "Standard access mode isolates users on one cluster and enforces their Unity Catalog permissions. Dedicated mode assigns the cluster to one user or group. No-isolation shared does not support Unity Catalog.",
     "The name says it is meant for sharing."),
    ("dbx-pools", "databricks", "medium", "What an instance pool saves",
     "What does an instance pool mainly save?",
     {"a": "DBUs: idle pool instances are free of Databricks charges and of cloud charges",
      "b": "Start-up time: clusters take ready VMs from the pool", "c": "Storage costs", "d": "Unity Catalog permissions"}, ["b"],
     "A pool keeps VMs ready so clusters start and scale faster. Idle instances cost no DBUs, but the cloud provider still bills the VMs.",
     "Think about waiting for a cluster to start."),
    ("dbx-sql-warehouse", "databricks", "easy", "Compute for a BI dashboard",
     "A Power BI report queries Databricks tables with SQL all day. Which compute is designed for that?",
     {"a": "A job cluster", "b": "A SQL warehouse", "c": "A single-node all-purpose cluster", "d": "An instance pool"}, ["b"],
     "SQL warehouses (classic, pro or serverless) serve SQL and BI tools; serverless starts in seconds and scales with the queries.",
     "BI tools speak SQL."),
    ("uc-namespace", "unity", "easy", "The three-level name",
     "In Unity Catalog, what are the three levels of a table's full name, in order? (three words separated by dots)",
     None, ["catalog.schema.table"],
     "Unity Catalog names objects catalog.schema.table (for example main.sales.orders). Schemas are also called databases.",
     "The first level is the object Unity Catalog is named after."),
    ("uc-privileges", "unity", "medium", "Privileges to read one table",
     "Which privileges does a user need to SELECT from main.sales.orders?",
     {"a": "SELECT on the table only", "b": "USE CATALOG on main, USE SCHEMA on main.sales and SELECT on the table",
      "c": "ALL PRIVILEGES on the metastore", "d": "MODIFY on the schema"}, ["b"],
     "Reading a table needs USE CATALOG on its catalog, USE SCHEMA on its schema and SELECT on the table (or SELECT granted higher up, which is inherited).",
     "Each level of the name has to be usable."),
    ("uc-managed-external", "unity", "medium", "Dropping a managed table",
     "What happens to the data files when you DROP a managed table in Unity Catalog?",
     {"a": "They stay; only the metadata is removed", "b": "Unity Catalog deletes them (after a retention period during which UNDROP can restore the table)",
      "c": "They move to a volume", "d": "They are converted to an external table"}, ["b"],
     "Unity Catalog manages the files of a managed table and deletes them after the drop (UNDROP works for a limited time). Dropping an external table leaves its files in place.",
     "Managed means Unity Catalog owns the files."),
    ("uc-volumes", "unity", "easy", "Where non-tabular files go",
     "Which Unity Catalog object governs non-tabular files (CSV drops, images, wheels)?",
     {"a": "A volume", "b": "A view", "c": "A storage credential", "d": "A function"}, ["a"],
     "Volumes govern files with the same catalog.schema.name path and grants (READ VOLUME, WRITE VOLUME) as tables.",
     "It lives next to tables in a schema."),
    ("formats-delta-log", "formats", "easy", "Where Delta keeps its history",
     "Which folder next to the Parquet files holds a Delta table's transaction log? (the folder name)",
     None, ["_delta_log", "_delta_log/"],
     "Delta records every commit as a JSON file in _delta_log, with Parquet checkpoints every few commits. Readers rebuild the table's current state from that log.",
     "It starts with an underscore."),
    ("formats-iceberg-metadata", "formats", "medium", "Iceberg's metadata tree",
     "How does Apache Iceberg find a table's data files?",
     {"a": "From a folder listing of the table's directory", "b": "Table metadata file -> manifest list -> manifests -> data files",
      "c": "From a JSON commit log replayed from the start", "d": "From a SQL database that stores the metadata"}, ["b"],
     "Iceberg reads a tree: the current metadata.json points to a snapshot's manifest list, which lists manifests, which list the data files with their statistics. No folder listing is needed.",
     "Think of a tree of files, not a log."),
    ("formats-partition-evolution", "formats", "hard", "Changing the partitioning",
     "Which format lets you change a table's partition scheme without rewriting existing data, with partitioning hidden from queries?",
     {"a": "Apache Iceberg", "b": "Plain Parquet folders", "c": "CSV", "d": "Hive tables"}, ["a"],
     "Iceberg's hidden partitioning derives partitions from column transforms (day(ts), bucket(16, id)); partition evolution applies a new scheme to new data while old files keep theirs. Delta's answer is liquid clustering.",
     "Its partitioning is described as hidden."),
    ("formats-vacuum", "formats", "medium", "What VACUUM removes",
     "What does VACUUM remove from a Delta table?",
     {"a": "Old rows in the latest version", "b": "Data files no longer referenced by the table and older than the retention period",
      "c": "The transaction log", "d": "Small files, by merging them"}, ["b"],
     "VACUUM deletes files that no current version references and that are older than the retention period (7 days by default). Time travel to versions needing those files stops working. Merging small files is OPTIMIZE.",
     "It cleans up after compaction and deletes."),
    ("formats-ducklake", "formats", "easy", "Where DuckLake keeps its metadata",
     "Where does DuckLake store a lake's metadata (tables, snapshots, file lists)?",
     {"a": "In JSON files next to the data", "b": "In a SQL database (DuckDB, SQLite, PostgreSQL or MySQL)",
      "c": "In Avro manifest files", "d": "Only in memory"}, ["b"],
     "DuckLake keeps its catalog in a SQL database and the data in Parquet files. A commit is one database transaction, which makes multi-table transactions straightforward.",
     "Its designers argued that metadata belongs in a database."),
    ("formats-uniform", "formats", "hard", "Reading Delta as Iceberg",
     "Which Delta Lake feature writes Iceberg metadata alongside the Delta log, so Iceberg readers can read the same table?",
     {"a": "Liquid clustering", "b": "Deletion vectors", "c": "UniForm", "d": "Change data feed"}, ["c"],
     "UniForm (universal format) generates Iceberg metadata for a Delta table from the same Parquet files; no data is copied.",
     "Its name means universal format."),
]


def starter(card):
    _, _, _, _, question, choices, _, _, _ = card
    lines = ["Concept check (no execution): nothing runs; the runtime checks your answer when you Submit.", "", question, ""]
    if choices:
        lines += [f"  {letter}) {text}" for letter, text in choices.items()]
        lines += ["", "Write the letter of your choice after \"answer:\" (several letters separated by commas if several are right), save, then Submit."]
    else:
        lines += ["Write your short answer after \"answer:\", save, then Submit."]
    return "\n".join(lines + ["answer:", ""])


def main():
    exercises, grading, mutants = [], {}, {}
    for card in CARDS:
        cid, topic, difficulty, title, question, choices, correct, why, hint = card
        ref_path, ref_title = REFERENCES[topic]
        kind = "choice" if choices else "text"
        exercises.append({
            "schema_version": 1, "id": "concept-" + cid, "version": "1", "title": title, "difficulty": difficulty,
            "topics": ["concepts", topic], "tags": ["concept-check", topic], "origin": "authored",
            "language": "quiz", "runtime": "datapass-quiz-v1", "prompt": question,
            "sections": [{"title": "Concept check (no execution)",
                          "body": "Nothing runs here: this platform cannot be executed locally. Answer in the file, save, and Submit; the runtime compares your answer with the pack's answer and explains it once you are right. The reference sheet (" + ref_title + ") covers the topic."}],
            "starter_source": starter(card),
            "fixtures": [{"id": "concept-" + cid + "-fixtures", "version": "1"}],
            "visible_checks": [{"id": "format", "description": "Your answer is well formed (Run checks only this)."}],
            "hidden_check_refs": ["answer"], "edge_check_refs": [],
            "hints": [hint, "Open the reference sheet: " + ref_title + "."],
            "solution": {"available": True, "reveal": "explicit"},
            "explanation": "The explanation comes with a correct submission, from the runtime.",
            "follow_ups": [], "canonical_placement": {"domain": "concepts", "topic": topic},
            "related_associations": ["practice/concepts"], "validator_version": "quiz-v1",
            "runtime_requirements": [], "provenance": {"source": "Authored for Datapass Workbench; checked against the vendors' documentation on 2026-09-26"},
            "constraints": {"truth": "Concept check: no execution; the answer is compared by the runtime."},
            "context_refs": [ref_path], "truth": "concept-check",
        })
        base = {"kind": kind, "choices": list(choices) if choices else []}
        answer = {"check": "answer", **base, "why": why, **({"correct": correct} if choices else {"accepted": correct})}
        grading["concept-" + cid] = {
            "solution": "answer: " + (", ".join(correct) if choices else correct[0]) + "\n",
            "fixtures": [
                {"id": "format", "visibility": "visible", "input_rows": [], "expected": [], "scenario": {"check": "format", **base}},
                {"id": "answer", "visibility": "hidden", "input_rows": [], "expected": [], "scenario": answer},
            ],
        }
        wrong = [c for c in (choices or {}) if c not in correct][:2] if choices else ["I don't know"]
        mutants["concept-" + cid] = ["answer: " + w + "\n" for w in wrong]
    PACK.mkdir(parents=True, exist_ok=True)
    dump = lambda name, data: (PACK / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dump("manifest.json", {"schema_version": 1, "id": "concepts-v1", "version": "1",
                           "title": "Concept checks: Fabric, Synapse, Databricks, Unity Catalog, table formats (no execution)",
                           "enabled": True, "provenance": {"source": "Authored for Datapass Workbench"}})
    dump("exercises.json", exercises)
    dump("grading.server.json", grading)
    dump("quality.json", {"flags": {"runnable_starters": True}, "mutants": mutants})
    print(f"concepts-v1: {len(exercises)} cards")


if __name__ == "__main__":
    main()
