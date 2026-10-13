// Cloud Lab › Pipelines editor (src/platform/factoryDocument.ts): path-based edits keep the file as written.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { pathToFileURL } from "node:url";
import * as esbuild from "esbuild";

const SAMPLES = {
  fabric: "samples/factory-lab/fabric/pl_retail_daily.DataPipeline/pipeline-content.json",
  adf: "samples/factory-lab/adf/pipeline/pl_retail_daily_adf.json",
  synapse: "samples/factory-lab/synapse/pipeline/pl_sqlpool_daily.json"
};

let dir;
let doc;
let run;
let types;
const texts = {};

before(async () => {
  dir = await mkdtemp(path.join(tmpdir(), "datapass-factory-editor-"));
  const build = async (entry, name) => {
    const outfile = path.join(dir, name);
    await esbuild.build({ entryPoints: [entry], bundle: true, platform: "node", format: "esm", target: "node20", outfile, logLevel: "silent" });
    return import(pathToFileURL(outfile).href);
  };
  doc = await build("src/platform/factoryDocument.ts", "factory-document.mjs");
  run = await build("src/platform/factoryRun.ts", "factory-run.mjs");
  types = await build("src/platform/factoryActivityTypes.ts", "factory-types.mjs");
  for (const [flavor, file] of Object.entries(SAMPLES)) texts[flavor] = await readFile(file, "utf8");
});

after(async () => {
  await rm(dir, { recursive: true, force: true });
});

const ok = result => {
  assert.equal(result.error, undefined, result.error);
  return result.text;
};
const value = text => JSON.parse(text);
const errors = (text, flavor) => doc.validatePipeline(value(text), flavor).filter(issue => issue.severity === "error");

test("the three flavor samples round-trip byte for byte and validate cleanly", () => {
  for (const [flavor, text] of Object.entries(texts)) {
    const history = doc.startHistory(text);
    assert.equal(history.present, text, flavor);
    // An edit and its undo give back the exact text; so does an edit and its inverse edit.
    const renamed = ok(doc.renameActivity(text, [], "Gold revenue", "Gold revenue v2"));
    assert.notEqual(renamed, text);
    assert.equal(doc.undo(doc.pushHistory(history, renamed)).present, text, flavor);
    assert.equal(ok(doc.renameActivity(renamed, [], "Gold revenue v2", "Gold revenue")), text, flavor);
    assert.deepEqual(errors(text, flavor), [], flavor);
    assert.equal(doc.contentHash(text), doc.contentHash(String(text)));
  }
});

test("edits keep unknown properties, key order, inline objects and indentation", () => {
  const text = texts.fabric;
  const added = ok(doc.addActivity(text, [], doc.newActivity("Wait", "Pause a little")));
  const before = value(text);
  const afterValue = value(added);
  // Only the new activity differs; everything else (annotations, policies, inline datasetSettings) is as it was.
  assert.deepEqual({ ...afterValue, properties: { ...afterValue.properties, activities: afterValue.properties.activities.slice(0, -1) } }, before);
  assert.deepEqual(Object.keys(afterValue.properties), Object.keys(before.properties));
  const last = before.properties.activities.at(-1);
  const cut = text.indexOf(`"name": "${last.name}"`);
  assert.equal(added.slice(0, cut), text.slice(0, cut), "text before the edit is unchanged");
  assert.ok(added.includes('"typeProperties": { "schema": "source", "table": "orders" }'), "inline objects stay inline");
  assert.match(added, /\r?\n      \{\r?\n        "name": "Pause a little",\r?\n        "type": "Wait",/,"new activity uses the file's indentation");

  // Unknown properties of an activity survive a property edit, and setting a nested path creates it in place.
  const withUnknown = ok(doc.setActivityProperty(text, [], "Copy orders to bronze", ["x-datapass-note"], { keep: [1, 2] }));
  const edited = ok(doc.setActivityProperty(withUnknown, [], "Copy orders to bronze", ["policy", "retry"], 3));
  const copy = value(edited).properties.activities[0];
  assert.deepEqual(copy["x-datapass-note"], { keep: [1, 2] });
  assert.equal(copy.policy.retry, 3);
  assert.equal(copy.policy.retryIntervalInSeconds, 60);
  const removed = ok(doc.setActivityProperty(edited, [], "Copy orders to bronze", ["x-datapass-note"], undefined));
  assert.equal(ok(doc.setActivityProperty(removed, [], "Copy orders to bronze", ["policy", "retry"], 1)), text);

  // CRLF files and tab indentation are written back with their own conventions.
  const crlf = '{\r\n\t"properties": {\r\n\t\t"activities": []\r\n\t}\r\n}\r\n';
  const grown = ok(doc.addActivity(crlf, [], doc.newActivity("Wait", "W1")));
  assert.ok(!/[^\r]\n/.test(grown), "CRLF kept");
  assert.match(grown, /\r\n\t\t\t\{\r\n\t\t\t\t"name": "W1"/);
  assert.equal(ok(doc.deleteActivities(grown, [], ["W1"])), crlf.replace('"activities": []', '"activities": []'));
});

test("rename updates the dependencies that point to the activity", () => {
  const renamed = ok(doc.renameActivity(texts.fabric, [], "Silver orders", "Silver orders clean"));
  const activities = value(renamed).properties.activities;
  assert.deepEqual(activities.find(a => a.name === "Gold revenue").dependsOn[0].activity, "Silver orders clean");
  assert.deepEqual(activities.find(a => a.name === "Email on notebook failure").dependsOn[0],
    { activity: "Silver orders clean", dependencyConditions: ["Failed"] });
  assert.deepEqual(errors(renamed, "fabric"), []);
  assert.match(doc.renameActivity(texts.fabric, [], "Silver orders", "Post to Teams").error, /already used/);
  assert.match(doc.renameActivity(texts.fabric, [], "Silver orders", "bad.name").error, /cannot contain/);
});

test("delete removes the activity and prunes dependencies on it", () => {
  const deleted = ok(doc.deleteActivities(texts.fabric, [], ["Silver orders"]));
  const activities = value(deleted).properties.activities;
  assert.equal(activities.some(a => a.name === "Silver orders"), false);
  assert.deepEqual(activities.find(a => a.name === "Gold revenue").dependsOn, []);
  assert.deepEqual(activities.find(a => a.name === "Email on notebook failure").dependsOn, []);
  assert.deepEqual(errors(deleted, "fabric"), []);
  // Inside a container level.
  const scope = [{ activity: "Has gold rows", key: "ifTrueActivities" }];
  const inner = ok(doc.deleteActivities(texts.fabric, scope, ["Post to Teams"]));
  assert.deepEqual(value(inner).properties.activities.find(a => a.name === "Has gold rows").typeProperties.ifTrueActivities, []);
});

test("connect, condition changes and disconnect; cycles and unknown conditions are refused", () => {
  const text = texts.adf;
  assert.match(doc.connectActivities(text, [], "Notify webhook", "Copy orders to bronze", "Succeeded").error, /cycle/);
  assert.match(doc.connectActivities(text, [], "Gold revenue", "Gold revenue", "Succeeded").error, /itself/);
  assert.match(doc.connectActivities(text, [], "Copy orders to bronze", "Notify webhook", "Done").error, /Unknown dependency condition/);
  const linked = ok(doc.connectActivities(text, [], "Silver orders", "Notify webhook", "Failed"));
  const notify = () => value(linked).properties.activities.find(a => a.name === "Notify webhook");
  assert.deepEqual(notify().dependsOn.map(d => d.activity), ["Gold revenue", "Silver orders"]);
  const both = ok(doc.connectActivities(linked, [], "Silver orders", "Notify webhook", "Skipped"));
  assert.deepEqual(value(both).properties.activities.at(-1).dependsOn[1].dependencyConditions, ["Failed", "Skipped"]);
  const one = ok(doc.disconnectActivities(both, [], "Silver orders", "Notify webhook", "Failed"));
  assert.deepEqual(value(one).properties.activities.at(-1).dependsOn[1].dependencyConditions, ["Skipped"]);
  const completed = ok(doc.setDependencyConditions(one, [], "Silver orders", "Notify webhook", ["Completed"]));
  assert.deepEqual(value(completed).properties.activities.at(-1).dependsOn[1].dependencyConditions, ["Completed"]);
  assert.equal(ok(doc.disconnectActivities(completed, [], "Silver orders", "Notify webhook")), text);
});

test("move into and out of containers keeps the activity's JSON and drops cross-level dependencies", () => {
  const text = texts.fabric;
  const into = [{ activity: "Has gold rows", key: "ifFalseActivities" }];
  const moved = ok(doc.moveActivity(text, [], "Email on notebook failure", into));
  const top = value(moved).properties.activities;
  assert.equal(top.some(a => a.name === "Email on notebook failure"), false);
  const inner = top.find(a => a.name === "Has gold rows").typeProperties.ifFalseActivities;
  const original = value(text).properties.activities.find(a => a.name === "Email on notebook failure");
  assert.deepEqual(inner.at(-1), { ...original, dependsOn: [] });
  assert.deepEqual(errors(moved, "fabric"), []);
  const back = ok(doc.moveActivity(moved, into, "Email on notebook failure", []));
  assert.deepEqual(value(back).properties.activities.at(-1), { ...original, dependsOn: [] });
  assert.match(doc.moveActivity(text, [], "Has gold rows", [{ activity: "Has gold rows", key: "ifTrueActivities" }]).error, /inside itself/);

  // Switch cases and ForEach levels; loops do not nest.
  let built = ok(doc.addActivity(text, [], doc.newActivity("Switch", "Route")));
  built = ok(doc.addSwitchCase(built, [], "Route", "daily"));
  built = ok(doc.addActivity(built, [{ activity: "Route", key: "case daily" }], doc.newActivity("Wait", "Daily wait")));
  built = ok(doc.addActivity(built, [], doc.newActivity("ForEach", "Each table")));
  assert.match(doc.addActivity(built, [{ activity: "Each table", key: "activities" }], doc.newActivity("Until", "Poll")).error, /cannot be nested/);
  built = ok(doc.moveActivity(built, [{ activity: "Route", key: "case daily" }], "Daily wait", [{ activity: "Each table", key: "activities" }]));
  const each = value(built).properties.activities.find(a => a.name === "Each table");
  assert.deepEqual(each.typeProperties.activities.map(a => a.name), ["Daily wait"]);
  const design = run.designView("fabric", "x", "factory/x.json", built);
  assert.deepEqual(design.activities.find(a => a.name === "Route").children.map(c => c.key), ["defaultActivities", "case daily"]);
});

test("undo and redo keep at most 100 earlier versions", () => {
  let history = doc.startHistory(texts.synapse);
  for (let index = 0; index < 120; index++) {
    history = doc.pushHistory(history, ok(doc.addActivity(history.present, [], doc.newActivity("Wait", `W${index}`))));
  }
  assert.equal(history.past.length, doc.HISTORY_LIMIT);
  let back = history;
  for (let index = 0; index < 150; index++) back = doc.undo(back);
  assert.equal(back.past.length, 0);
  assert.equal(value(back.present).properties.activities.filter(a => a.type === "Wait").length, 20);
  assert.equal(doc.redo(doc.undo(history)).present, history.present);
  assert.equal(doc.pushHistory(doc.undo(history), texts.synapse).future.length, 0, "a new edit clears redo");
});

test("validation reports cycles, dangling and duplicate names, unknown conditions, required properties and products", () => {
  const pipeline = activities => JSON.stringify({ properties: { activities } }, null, 2);
  const issues = doc.validatePipeline(value(pipeline([
    { name: "A", type: "Wait", dependsOn: [{ activity: "B", dependencyConditions: ["Succeeded"] }], typeProperties: { waitTimeInSeconds: 1 } },
    { name: "B", type: "Wait", dependsOn: [{ activity: "A", dependencyConditions: ["Done"] }], typeProperties: { waitTimeInSeconds: 1 } },
    { name: "C", type: "Wait", dependsOn: [{ activity: "Ghost" }], typeProperties: { waitTimeInSeconds: 1 } },
    { name: "R", type: "Copy", typeProperties: { source: {} } },
    { name: "N", type: "TridentNotebook", typeProperties: { notebookId: "x" } },
    { name: "L", type: "ForEach", typeProperties: { items: "@x", activities: [{ name: "U", type: "Until", typeProperties: { expression: "@true", activities: [] } }] } },
    { name: "R", type: "Wait", typeProperties: { waitTimeInSeconds: "@activity('Old name').output" } },
    { name: "X", type: "dbtJob", typeProperties: {} }
  ])), "adf").map(issue => `${issue.severity} ${issue.path}: ${issue.message}`);
  const has = pattern => assert.ok(issues.some(issue => pattern.test(issue)), `${pattern} in\n${issues.join("\n")}`);
  has(/error : Dependency cycle between A, B/);
  has(/error B: Unknown dependency condition\(s\) Done/);
  has(/error C: Depends on 'Ghost'/);
  has(/error R: Duplicate activity name 'R'/);
  has(/error R: Copy data needs typeProperties.sink/);
  has(/error N: 'TridentNotebook' \(Notebook\) is not in Azure Data Factory; use DatabricksNotebook/);
  has(/error L\/U: Until cannot be nested/);
  has(/warning : An expression reads activity\('Old name'\)/);
  has(/error X: Activity type 'dbtJob' is not simulated/);
});

test("the palette follows runtime/factorylab/activities.py per product", () => {
  const fabric = types.factoryActivityTypesFor("fabric").map(t => t.name);
  const adf = types.factoryActivityTypesFor("adf").map(t => t.name);
  assert.ok(fabric.includes("TridentNotebook") && fabric.includes("InvokePipeline") && !fabric.includes("ExecuteDataFlow"));
  assert.ok(adf.includes("ExecuteDataFlow") && !adf.includes("Teams") && !adf.includes("SqlPoolStoredProcedure"));
  assert.ok(types.factoryActivityTypesFor("synapse").some(t => t.name === "SqlPoolStoredProcedure"));
  assert.ok(!types.FACTORY_ACTIVITY_TYPES.some(t => /dbt/i.test(t.name)));
});

test("design view hash and reload marker follow the text", () => {
  const design = run.designView("adf", "pl_retail_daily_adf", "factory/adf/pipeline/pl_retail_daily_adf.json", texts.adf);
  assert.equal(design.text, texts.adf);
  assert.equal(design.hash, doc.contentHash(texts.adf));
  assert.equal(design.reloadSeq, 0);
  run.requestFactoryReload("factory/adf/pipeline/pl_retail_daily_adf.json");
  assert.equal(run.designView("adf", "pl_retail_daily_adf", "factory/adf/pipeline/pl_retail_daily_adf.json", texts.adf).reloadSeq, 1);
});
