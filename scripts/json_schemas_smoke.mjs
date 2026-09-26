// JSON schemas (schemas/, contributes.jsonValidation): every shipped file of each kind validates against its
// schema, a broken one does not, and package.json points each schema at the right files. The generated schemas'
// freshness is checked by `python scripts/authoring/gen_json_schemas.py --check` (runtime job).
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import * as esbuild from "esbuild";

const dir = await mkdtemp(path.join(tmpdir(), "datapass-schemas-"));
const json = async file => JSON.parse(await readFile(file, "utf8"));

try {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validator = async name => ajv.compile(await json(`schemas/${name}.schema.json`));
  const check = (validate, doc, label) => {
    assert.ok(validate(doc), `${label}: ${ajv.errorsText(validate.errors)}`);
  };

  // .datapass/project.json: the manifest the extension creates.
  const outfile = path.join(dir, "manifest.mjs");
  await esbuild.build({ entryPoints: ["src/project/projectManifestModel.ts"], bundle: true, platform: "node", format: "esm", outfile, logLevel: "silent" });
  const { createDefaultProjectManifest, validateProjectManifest } = await import(pathToFileURL(outfile).href);
  const project = await validator("project");
  const manifest = createDefaultProjectManifest("My Project");
  check(project, manifest, "default project.json");
  for (const broken of [{ ...manifest, schemaVersion: 2 }, { ...manifest, runtime: { storage: "sqlite" } }, { schemaVersion: 1, project: { id: "x" } }]) {
    assert.ok(!project(broken), `a broken project.json fails: ${JSON.stringify(broken).slice(0, 60)}`);
    assert.ok(validateProjectManifest(broken).length > 0, "the extension's validator agrees");
  }

  // bi/model.json: the BI Lab sample star model.
  const bi = await validator("bi-model");
  const model = await json("samples/bi-lab/model.json");
  check(bi, model, "samples/bi-lab/model.json");
  assert.ok(!bi({ ...model, tables: [{ ...model.tables[0], role: "cube" }] }), "an unknown table role fails");
  assert.ok(!bi({ ...model, extra: 1 }), "an unknown key fails");

  // mission.json: every shipped mission, the API Lab pack with its own schema.
  const mission = await validator("mission");
  const apiMission = await validator("api-mission");
  let missions = 0;
  for (const pack of await readdir("content/missions", { withFileTypes: true })) {
    if (!pack.isDirectory()) continue;
    const validate = pack.name === "api-v1" ? apiMission : mission;
    for (const id of (await json(`content/missions/${pack.name}/pack.json`)).missions) {
      const file = `content/missions/${pack.name}/${id}/mission.json`;
      const doc = await json(file);
      check(validate, doc, file);
      assert.ok(!validate({ ...doc, surprise: true }), `${file}: an unknown key fails`);
      missions += 1;
    }
  }
  assert.ok(missions >= 20, `missions checked: ${missions}`);

  // Exercise pack manifests.
  const packSchema = await validator("exercise-pack");
  let packs = 0;
  for (const pack of await readdir("content/exercise-packs", { withFileTypes: true })) {
    if (!pack.isDirectory()) continue;
    check(packSchema, await json(`content/exercise-packs/${pack.name}/manifest.json`), `${pack.name}/manifest.json`);
    packs += 1;
  }
  assert.ok(!packSchema({ schema_version: 1, id: "a b", version: "1", title: "x" }), "a bad pack id fails");

  // package.json: each schema is contributed for its files, and the API Lab missions only get theirs.
  const pkg = await json("package.json");
  const contributed = Object.fromEntries(pkg.contributes.jsonValidation.map(entry => [entry.url, [entry.fileMatch].flat()]));
  for (const name of ["project", "bi-model", "mission", "api-mission", "exercise-pack"]) {
    assert.ok(contributed[`./schemas/${name}.schema.json`], `${name} is contributed`);
  }
  assert.ok(contributed["./schemas/mission.schema.json"].includes("!**/content/missions/api-v1/*/mission.json"), "API missions excluded from the missionlab schema");
  assert.ok(contributed["./schemas/project.schema.json"].includes("**/.datapass/project.json"));
  assert.ok(contributed["./schemas/bi-model.schema.json"].includes("**/bi/model.json"));
  const ignore = await readFile(".vscodeignore", "utf8");
  assert.ok(!/^schemas\b/m.test(ignore), "schemas/ ships in the VSIX");

  console.log(`JSON schemas smoke passed: project, star model, ${missions} missions, ${packs} pack manifests.`);
} finally {
  await rm(dir, { recursive: true, force: true });
}
