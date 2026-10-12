/**
 * Cloud Lab › Pipelines editor: path-based edits on a pipeline JSON file (Fabric pipeline-content.json, Azure Data
 * Factory / Synapse pipeline/*.json).
 *
 * The document is its text. Every edit is a small text replacement at a JSON path, so everything the editor does
 * not model (unknown properties, key order, inline objects, typeProperties it has no form for) stays byte for byte
 * as written, and an unedited document serializes to exactly the text it was read from. New values are written with
 * the file's own indentation and line endings. Pure module: no VS Code, no DOM, no Node API (the webview and the
 * extension host both use it).
 */
import type { FactoryFlavor } from "../webview/contracts";
import { FACTORY_ACTIVITY_TYPES, FACTORY_CONTAINER_KEYS, FACTORY_FLAVOR_LABELS } from "./factoryActivityTypes";

export type JsonPath = readonly (string | number)[];
export type EditResult = { text: string; error?: undefined } | { text?: undefined; error: string };

/** Dependency conditions of Data Factory (Completed = Succeeded or Failed). */
export const DEPENDENCY_CONDITIONS = ["Succeeded", "Failed", "Skipped", "Completed"] as const;
export type DependencyCondition = (typeof DEPENDENCY_CONDITIONS)[number];
/** Undo keeps at most this many earlier versions. */
export const HISTORY_LIMIT = 100;
/** The runtime refuses longer names and these characters (runtime/factorylab/loader.py). */
export const ACTIVITY_NAME_MAX = 55;
const BAD_NAME = /[.+?/<>*%&:\\]/;

// ---------------------------------------------------------------------------------------------------------------
// JSON text tree with offsets

interface JNode {
  kind: "object" | "array" | "string" | "number" | "literal";
  start: number;
  end: number;
  props?: JProp[];
  items?: JNode[];
}

interface JProp {
  key: string;
  start: number;
  value: JNode;
}

class JsonScanner {
  pos = 0;
  constructor(readonly text: string) {}

  fail(message: string): never {
    throw new SyntaxError(`${message} at offset ${this.pos}`);
  }

  space(): void {
    while (this.pos < this.text.length && /[ \t\r\n﻿]/.test(this.text[this.pos])) this.pos++;
  }

  value(): JNode {
    this.space();
    const char = this.text[this.pos];
    const start = this.pos;
    if (char === "{") {
      this.pos++;
      const props: JProp[] = [];
      this.space();
      if (this.text[this.pos] === "}") {
        this.pos++;
        return { kind: "object", start, end: this.pos, props };
      }
      for (;;) {
        this.space();
        const keyStart = this.pos;
        if (this.text[this.pos] !== '"') this.fail("Expected a property name");
        const key = JSON.parse(this.text.slice(keyStart, this.string())) as string;
        this.space();
        if (this.text[this.pos] !== ":") this.fail("Expected ':'");
        this.pos++;
        props.push({ key, start: keyStart, value: this.value() });
        this.space();
        if (this.text[this.pos] === ",") { this.pos++; continue; }
        if (this.text[this.pos] === "}") { this.pos++; return { kind: "object", start, end: this.pos, props }; }
        this.fail("Expected ',' or '}'");
      }
    }
    if (char === "[") {
      this.pos++;
      const items: JNode[] = [];
      this.space();
      if (this.text[this.pos] === "]") {
        this.pos++;
        return { kind: "array", start, end: this.pos, items };
      }
      for (;;) {
        items.push(this.value());
        this.space();
        if (this.text[this.pos] === ",") { this.pos++; continue; }
        if (this.text[this.pos] === "]") { this.pos++; return { kind: "array", start, end: this.pos, items }; }
        this.fail("Expected ',' or ']'");
      }
    }
    if (char === '"') return { kind: "string", start, end: this.string() };
    const literal = /^(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(this.text.slice(this.pos, this.pos + 400));
    if (!literal) this.fail("Unexpected character");
    this.pos += literal[0].length;
    return { kind: /^[-\d]/.test(literal[0]) ? "number" : "literal", start, end: this.pos };
  }

  /** Scan a string starting at pos; returns its end offset (after the closing quote). */
  string(): number {
    this.pos++;
    while (this.pos < this.text.length) {
      const char = this.text[this.pos];
      if (char === "\\") this.pos += 2;
      else if (char === '"') return ++this.pos;
      else this.pos++;
    }
    return this.fail("Unterminated string");
  }
}

function parseTree(text: string): JNode {
  const scanner = new JsonScanner(text);
  const root = scanner.value();
  scanner.space();
  if (scanner.pos !== text.length) scanner.fail("Unexpected text after the JSON value");
  return root;
}

function nodeAt(root: JNode, path: JsonPath): JNode | undefined {
  let current: JNode | undefined = root;
  for (const step of path) {
    if (!current) return undefined;
    if (typeof step === "number") current = current.kind === "array" ? current.items![step] : undefined;
    else current = current.kind === "object" ? current.props!.find(prop => prop.key === step)?.value : undefined;
  }
  return current;
}

// ---------------------------------------------------------------------------------------------------------------
// Formatting

export interface JsonFormat {
  indent: string;
  eol: "\n" | "\r\n";
}

/** The file's indentation unit and line ending (two spaces and \n when the file does not say). */
export function detectFormat(text: string): JsonFormat {
  const eol = text.includes("\r\n") ? "\r\n" : "\n";
  const indent = /[{[][ \t]*\r?\n([ \t]+)\S/.exec(text)?.[1] ?? "  ";
  return { indent, eol };
}

function lineIndent(text: string, offset: number): string {
  const lineStart = text.lastIndexOf("\n", offset - 1) + 1;
  return /^[ \t]*/.exec(text.slice(lineStart))![0];
}

function isMultiline(text: string, node: JNode): boolean {
  return text.slice(node.start, node.end).includes("\n");
}

/** A value on one line, spaced like the samples' inline objects: { "a": 1, "b": [1, 2] }. */
function inlineJson(value: unknown): string {
  if (Array.isArray(value)) return value.length ? `[${value.map(inlineJson).join(", ")}]` : "[]";
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined);
    return entries.length ? `{ ${entries.map(([key, item]) => `${JSON.stringify(key)}: ${inlineJson(item)}`).join(", ")} }` : "{}";
  }
  return JSON.stringify(value ?? null);
}

function blockJson(value: unknown, base: string, format: JsonFormat): string {
  return JSON.stringify(value ?? null, null, format.indent).split("\n").join(format.eol + base);
}

/** Re-indent a raw JSON fragment written at `from` so it sits at `to` (lines after the first). */
function reindent(fragment: string, from: string, to: string, format: JsonFormat): string {
  const lines = fragment.split(/\r?\n/);
  return lines.map((line, index) => index === 0 ? line : (line.startsWith(from) ? to + line.slice(from.length) : line)).join(format.eol);
}

// ---------------------------------------------------------------------------------------------------------------
// Text edits at a JSON path

function splice(text: string, start: number, end: number, insert: string): string {
  return text.slice(0, start) + insert + text.slice(end);
}

/** Replace the value at `path` (which must exist). */
export function replaceValue(text: string, path: JsonPath, value: unknown): string {
  return replaceRaw(text, path, raw => {
    const node = raw.node;
    return isMultiline(text, node) || (value !== null && typeof value === "object" && !raw.inline)
      ? blockJson(value, lineIndent(text, node.start), detectFormat(text))
      : inlineJson(value);
  });
}

function replaceRaw(text: string, path: JsonPath, make: (raw: { node: JNode; inline: boolean }) => string): string {
  const root = parseTree(text);
  const node = nodeAt(root, path);
  if (!node) throw new Error(`Nothing at ${path.join(".")}`);
  const parent = path.length ? nodeAt(root, path.slice(0, -1)) : undefined;
  const inline = !!parent && !isMultiline(text, parent);
  return splice(text, node.start, node.end, make({ node, inline }));
}

/** Set `key` of the object at `objectPath`: replaced in place when present, appended otherwise. */
export function setProperty(text: string, objectPath: JsonPath, key: string, value: unknown): string {
  const root = parseTree(text);
  const object = nodeAt(root, objectPath);
  if (!object || object.kind !== "object") throw new Error(`No object at ${objectPath.join(".") || "root"}`);
  if (object.props!.some(prop => prop.key === key)) return replaceValue(text, [...objectPath, key], value);
  const format = detectFormat(text);
  if (!object.props!.length) {
    return splice(text, object.start, object.end, blockJson({ [key]: value }, lineIndent(text, object.start), format));
  }
  const last = object.props![object.props!.length - 1];
  if (!isMultiline(text, object)) {
    return splice(text, last.value.end, last.value.end, `, ${JSON.stringify(key)}: ${inlineJson(value)}`);
  }
  const indent = lineIndent(text, last.start);
  return splice(text, last.value.end, last.value.end,
    `,${format.eol}${indent}${JSON.stringify(key)}: ${blockJson(value, indent, format)}`);
}

/** Remove `key` from the object at `objectPath` (no-op when absent). */
export function removeProperty(text: string, objectPath: JsonPath, key: string): string {
  const object = nodeAt(parseTree(text), objectPath);
  if (!object || object.kind !== "object") return text;
  const props = object.props!;
  const index = props.findIndex(prop => prop.key === key);
  if (index < 0) return text;
  if (props.length === 1) return splice(text, object.start, object.end, "{}");
  return index > 0
    ? splice(text, props[index - 1].value.end, props[index].value.end, "")
    : splice(text, props[0].start, props[1].start, "");
}

/** Insert `raw` (JSON text written at indentation `rawIndent`) into the array at `arrayPath`; index -1 = end. */
function insertRawItem(text: string, arrayPath: JsonPath, raw: string, rawIndent: string, index = -1): string {
  const array = nodeAt(parseTree(text), arrayPath);
  if (!array || array.kind !== "array") throw new Error(`No array at ${arrayPath.join(".")}`);
  const format = detectFormat(text);
  const items = array.items!;
  if (!items.length) {
    const base = lineIndent(text, array.start);
    const inner = base + format.indent;
    return splice(text, array.start, array.end, `[${format.eol}${inner}${reindent(raw, rawIndent, inner, format)}${format.eol}${base}]`);
  }
  const multiline = isMultiline(text, array);
  const at = index < 0 || index >= items.length ? items.length : index;
  const anchor = items[Math.min(at, items.length - 1)];
  const indent = lineIndent(text, anchor.start);
  const value = multiline ? reindent(raw, rawIndent, indent, format) : raw;
  const separator = multiline ? `,${format.eol}${indent}` : ", ";
  return at === items.length
    ? splice(text, items[items.length - 1].end, items[items.length - 1].end, separator + value)
    : splice(text, items[at].start, items[at].start, value + separator);
}

/** Insert a value into the array at `arrayPath`; index -1 = end. */
export function insertItem(text: string, arrayPath: JsonPath, value: unknown, index = -1): string {
  const format = detectFormat(text);
  const array = nodeAt(parseTree(text), arrayPath);
  const multiline = array ? isMultiline(text, array) || !array.items!.length : true;
  const raw = multiline ? blockJson(value, "", format) : inlineJson(value);
  return insertRawItem(text, arrayPath, raw, "", index);
}

/** Remove item `index` of the array at `arrayPath`. */
export function removeItem(text: string, arrayPath: JsonPath, index: number): string {
  const array = nodeAt(parseTree(text), arrayPath);
  if (!array || array.kind !== "array" || !array.items![index]) return text;
  const items = array.items!;
  if (items.length === 1) return splice(text, array.start, array.end, "[]");
  return index > 0
    ? splice(text, items[index - 1].end, items[index].end, "")
    : splice(text, items[0].start, items[1].start, "");
}

/** Set the value at `path`, creating missing objects on the way (an array index must exist). */
export function setPath(text: string, path: JsonPath, value: unknown): string {
  const root = parseTree(text);
  if (nodeAt(root, path)) return replaceValue(text, path, value);
  let existing = path.length - 1;
  while (existing > 0 && !nodeAt(root, path.slice(0, existing))) existing--;
  const parentPath = path.slice(0, existing);
  const parent = nodeAt(root, parentPath);
  const key = path[existing];
  if (!parent || parent.kind !== "object" || typeof key !== "string") throw new Error(`Cannot create ${path.join(".")}`);
  let nested: unknown = value;
  for (let index = path.length - 1; index > existing; index--) {
    const step = path[index];
    if (typeof step !== "string") throw new Error(`Cannot create ${path.join(".")}`);
    nested = { [step]: nested };
  }
  return setProperty(text, parentPath, key, nested);
}

/** Remove the value at `path` (property or array item); no-op when absent. */
export function removePath(text: string, path: JsonPath): string {
  if (!path.length) return text;
  const last = path[path.length - 1];
  return typeof last === "number" ? removeItem(text, path.slice(0, -1), last) : removeProperty(text, path.slice(0, -1), last);
}

// ---------------------------------------------------------------------------------------------------------------
// Pipeline model

type Raw = Record<string, unknown>;

/** One drill-down step: the container activity's name and its branch (activities, ifTrueActivities, "case <v>"...). */
export interface ScopeStep {
  activity: string;
  key: string;
}
export type Scope = readonly ScopeStep[];

export function parsePipeline(text: string): { value?: Raw; error?: string } {
  try {
    parseTree(text);
    const value = JSON.parse(text) as unknown;
    if (!value || typeof value !== "object" || Array.isArray(value)) return { error: "The pipeline file must be a JSON object." };
    return { value: value as Raw };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

function asRecord(value: unknown): Raw {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Raw : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function getAt(value: unknown, path: JsonPath): unknown {
  let current = value;
  for (const step of path) {
    if (typeof step === "number") current = Array.isArray(current) ? current[step] : undefined;
    else current = current && typeof current === "object" && !Array.isArray(current) ? (current as Raw)[step] : undefined;
  }
  return current;
}

/** JSON path of the top-level activities array: properties.activities, or activities in a bare pipeline. */
export function rootActivitiesPath(value: Raw): JsonPath {
  return value.properties && typeof value.properties === "object" ? ["properties", "activities"] : ["activities"];
}

/** JSON path of the activity array a scope designates (it may not exist yet, for an empty branch). */
export function scopePath(value: Raw, scope: Scope): JsonPath | undefined {
  let path: JsonPath = rootActivitiesPath(value);
  for (const step of scope) {
    const index = list(getAt(value, path)).findIndex(item => asRecord(item).name === step.activity);
    if (index < 0) return undefined;
    const props: JsonPath = [...path, index, "typeProperties"];
    if (step.key.startsWith("case ")) {
      const caseValue = step.key.slice(5);
      const caseIndex = list(getAt(value, [...props, "cases"])).findIndex(entry => String(asRecord(entry).value) === caseValue);
      if (caseIndex < 0) return undefined;
      path = [...props, "cases", caseIndex, "activities"];
    } else {
      path = [...props, step.key];
    }
  }
  return path;
}

function activitiesIn(value: Raw, scope: Scope): Raw[] {
  const path = scopePath(value, scope);
  return path ? list(getAt(value, path)).map(asRecord) : [];
}

/** Every activity name of the pipeline, at any level (the runtime wants them unique across the pipeline). */
export function allActivityNames(value: Raw): string[] {
  const names: string[] = [];
  const walk = (activities: unknown) => {
    for (const item of list(activities)) {
      const activity = asRecord(item);
      if (typeof activity.name === "string") names.push(activity.name);
      const props = asRecord(activity.typeProperties);
      for (const key of ["activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities"]) walk(props[key]);
      for (const entry of list(props.cases)) walk(asRecord(entry).activities);
    }
  };
  walk(getAt(value, rootActivitiesPath(value)));
  return names;
}

/** Why a name cannot be used, or undefined. */
export function activityNameProblem(name: string, value: Raw, except?: string): string | undefined {
  if (!name.trim()) return "An activity needs a name.";
  if (name !== name.trim()) return "Activity names cannot start or end with a space.";
  if (name.length > ACTIVITY_NAME_MAX) return `Activity names are at most ${ACTIVITY_NAME_MAX} characters.`;
  if (BAD_NAME.test(name)) return "Activity names cannot contain . + ? / < > * % & : \\";
  if (name !== except && allActivityNames(value).includes(name)) return `'${name}' is already used: activity names are unique across the whole pipeline.`;
  return undefined;
}

/** A free default name like the products give: "Copy data1", "ForEach2". */
export function defaultActivityName(type: string, value: Raw): string {
  const spec = FACTORY_ACTIVITY_TYPES.find(item => item.name === type);
  const base = (spec?.label ?? type).replace(/\s*\(.*$/, "").replace(/[.+?/<>*%&:\\]/g, "").slice(0, ACTIVITY_NAME_MAX - 3) || "Activity";
  const used = new Set(allActivityNames(value));
  let index = 1;
  while (used.has(`${base}${index}`)) index++;
  return `${base}${index}`;
}

/**
 * A new activity of `type`: empty inner activity arrays for containers, a default policy for work activities, and
 * no invented settings (validation lists the required ones still missing).
 */
export function newActivity(type: string, name: string): Raw {
  const spec = FACTORY_ACTIVITY_TYPES.find(item => item.name === type);
  const typeProperties: Raw = {};
  for (const key of FACTORY_CONTAINER_KEYS[type] ?? []) typeProperties[key] = [];
  if (type === "Switch") typeProperties.cases = [];
  if (type === "Wait") typeProperties.waitTimeInSeconds = 1;
  const activity: Raw = { name, type, dependsOn: [] };
  if (spec && !spec.control) {
    activity.policy = { timeout: "0.12:00:00", retry: 0, retryIntervalInSeconds: 30, secureOutput: false, secureInput: false };
  }
  activity.typeProperties = typeProperties;
  return activity;
}

function withPipeline(text: string, edit: (value: Raw) => EditResult): EditResult {
  const parsed = parsePipeline(text);
  if (parsed.error || !parsed.value) return { error: parsed.error ?? "Not a pipeline" };
  try {
    return edit(parsed.value);
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

/** Make sure the activity array of `scope` exists (an empty branch has none yet); returns its path. */
function ensureScopeArray(text: string, value: Raw, scope: Scope): { text: string; path: JsonPath } {
  const path = scopePath(value, scope);
  if (!path) throw new Error("That container no longer exists.");
  if (Array.isArray(getAt(value, path))) return { text, path };
  return { text: setPath(text, path, []), path };
}

/** Add an activity at the end of a level. */
export function addActivity(text: string, scope: Scope, activity: Raw): EditResult {
  return withPipeline(text, value => {
    const name = String(activity.name ?? "");
    const problem = activityNameProblem(name, value);
    if (problem) return { error: problem };
    const loop = loopProblem(value, scope, String(activity.type));
    if (loop) return { error: loop };
    const ensured = ensureScopeArray(text, value, scope);
    return { text: insertItem(ensured.text, ensured.path, activity) };
  });
}

function indexIn(value: Raw, scope: Scope, name: string): { path: JsonPath; index: number } {
  const path = scopePath(value, scope);
  const index = path ? list(getAt(value, path)).findIndex(item => asRecord(item).name === name) : -1;
  if (!path || index < 0) throw new Error(`No activity '${name}' at this level.`);
  return { path, index };
}

/** Rename an activity; the dependsOn entries of its siblings follow. */
export function renameActivity(text: string, scope: Scope, from: string, to: string): EditResult {
  if (from === to) return { text };
  return withPipeline(text, value => {
    const problem = activityNameProblem(to, value, from);
    if (problem) return { error: problem };
    const { path, index } = indexIn(value, scope, from);
    let next = replaceValue(text, [...path, index, "name"], to);
    list(getAt(value, path)).forEach((item, sibling) => {
      list(asRecord(item).dependsOn).forEach((dependency, entry) => {
        if (asRecord(dependency).activity === from) next = replaceValue(next, [...path, sibling, "dependsOn", entry, "activity"], to);
      });
    });
    return { text: next };
  });
}

/** Remove the dependsOn entries of the siblings at `path` that point to one of `names`. */
function pruneDependencies(text: string, path: JsonPath, names: ReadonlySet<string>): string {
  const value = JSON.parse(text) as Raw;
  let next = text;
  const siblings = list(getAt(value, path));
  for (let sibling = siblings.length - 1; sibling >= 0; sibling--) {
    const dependencies = list(asRecord(siblings[sibling]).dependsOn);
    for (let entry = dependencies.length - 1; entry >= 0; entry--) {
      if (names.has(String(asRecord(dependencies[entry]).activity))) next = removeItem(next, [...path, sibling, "dependsOn"], entry);
    }
  }
  return next;
}

/** Delete activities of one level (with everything inside them); dependencies on them are removed. */
export function deleteActivities(text: string, scope: Scope, names: readonly string[]): EditResult {
  return withPipeline(text, value => {
    const path = scopePath(value, scope);
    if (!path) return { error: "That container no longer exists." };
    const items = list(getAt(value, path));
    const indexes = names.map(name => items.findIndex(item => asRecord(item).name === name)).filter(index => index >= 0);
    if (!indexes.length) return { error: "Nothing to delete." };
    let next = text;
    for (const index of [...indexes].sort((a, b) => b - a)) next = removeItem(next, path, index);
    return { text: pruneDependencies(next, path, new Set(names)) };
  });
}

/** Would `to` (transitively) depend on itself if it depended on `from`? */
function reaches(activities: readonly Raw[], from: string, to: string): boolean {
  const parents = new Map(activities.map(activity => [String(activity.name), list(activity.dependsOn).map(d => String(asRecord(d).activity))]));
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const current = stack.pop()!;
    if (current === to) return true;
    if (seen.has(current)) continue;
    seen.add(current);
    stack.push(...(parents.get(current) ?? []));
  }
  return false;
}

/** `to` runs after `from` ends with `condition`. Refused when it would make a cycle. */
export function connectActivities(text: string, scope: Scope, from: string, to: string, condition: string): EditResult {
  if (!(DEPENDENCY_CONDITIONS as readonly string[]).includes(condition)) {
    return { error: `Unknown dependency condition '${condition}': use ${DEPENDENCY_CONDITIONS.join(", ")}.` };
  }
  if (from === to) return { error: "An activity cannot depend on itself." };
  return withPipeline(text, value => {
    const activities = activitiesIn(value, scope);
    if (!activities.some(activity => activity.name === from)) return { error: `No activity '${from}' at this level: dependencies only link siblings.` };
    const { path, index } = indexIn(value, scope, to);
    if (reaches(activities, from, to)) return { error: `'${to}' already runs before '${from}': this dependency would make a cycle.` };
    const target = activities[index];
    const dependencies = list(target.dependsOn);
    const entry = dependencies.findIndex(dependency => asRecord(dependency).activity === from);
    if (entry < 0) {
      if (!Array.isArray(target.dependsOn)) return { text: setProperty(text, [...path, index], "dependsOn", [{ activity: from, dependencyConditions: [condition] }]) };
      return { text: insertItem(text, [...path, index, "dependsOn"], { activity: from, dependencyConditions: [condition] }) };
    }
    const current = asRecord(dependencies[entry]);
    const conditions = Array.isArray(current.dependencyConditions) ? current.dependencyConditions.map(String) : [];
    if (conditions.includes(condition)) return { text };
    if (!Array.isArray(current.dependencyConditions)) {
      return { text: setProperty(text, [...path, index, "dependsOn", entry], "dependencyConditions", [condition]) };
    }
    return { text: insertItem(text, [...path, index, "dependsOn", entry, "dependencyConditions"], condition) };
  });
}

/** Set the conditions of the dependency `to` → `from` (an empty list removes the dependency). */
export function setDependencyConditions(text: string, scope: Scope, from: string, to: string, conditions: readonly string[]): EditResult {
  const unknown = conditions.filter(condition => !(DEPENDENCY_CONDITIONS as readonly string[]).includes(condition));
  if (unknown.length) return { error: `Unknown dependency condition(s) ${unknown.join(", ")}: use ${DEPENDENCY_CONDITIONS.join(", ")}.` };
  return withPipeline(text, value => {
    const { path, index } = indexIn(value, scope, to);
    const dependencies = list(asRecord(list(getAt(value, path))[index]).dependsOn);
    const entry = dependencies.findIndex(dependency => asRecord(dependency).activity === from);
    if (entry < 0) return conditions.length ? connectActivities(text, scope, from, to, conditions[0]) : { text };
    if (!conditions.length) return { text: removeItem(text, [...path, index, "dependsOn"], entry) };
    return { text: setPath(text, [...path, index, "dependsOn", entry, "dependencyConditions"], [...conditions]) };
  });
}

/** Remove a dependency, or only one of its conditions. */
export function disconnectActivities(text: string, scope: Scope, from: string, to: string, condition?: string): EditResult {
  return withPipeline(text, value => {
    const { path, index } = indexIn(value, scope, to);
    const dependencies = list(asRecord(list(getAt(value, path))[index]).dependsOn);
    const entry = dependencies.findIndex(dependency => asRecord(dependency).activity === from);
    if (entry < 0) return { error: `'${to}' does not depend on '${from}'.` };
    const conditions = list(asRecord(dependencies[entry]).dependencyConditions).map(String);
    if (!condition || conditions.length <= 1 || !conditions.includes(condition)) {
      return { text: removeItem(text, [...path, index, "dependsOn"], entry) };
    }
    return { text: removeItem(text, [...path, index, "dependsOn", entry, "dependencyConditions"], conditions.indexOf(condition)) };
  });
}

/** ForEach and Until cannot run inside ForEach or Until (the runtime's rule, as in Data Factory). */
function loopProblem(value: Raw, scope: Scope, type: string): string | undefined {
  if (type !== "ForEach" && type !== "Until") return undefined;
  for (let depth = 0; depth < scope.length; depth++) {
    const path = scopePath(value, scope.slice(0, depth));
    const container = path ? list(getAt(value, path)).map(asRecord).find(item => item.name === scope[depth].activity) : undefined;
    if (container && (container.type === "ForEach" || container.type === "Until")) {
      return `${type} cannot be nested in ForEach or Until: call a child pipeline (Execute pipeline / Invoke pipeline) for the inner loop.`;
    }
  }
  return undefined;
}

/** Does the activity (or anything inside it) contain a ForEach or Until? */
function containsLoop(activity: Raw): boolean {
  const props = asRecord(activity.typeProperties);
  const inner = [
    ...["activities", "ifTrueActivities", "ifFalseActivities", "defaultActivities"].flatMap(key => list(props[key])),
    ...list(props.cases).flatMap(entry => list(asRecord(entry).activities))
  ].map(asRecord);
  return inner.some(item => item.type === "ForEach" || item.type === "Until" || containsLoop(item));
}

/**
 * Move an activity to another level (into or out of a container). Its own dependencies are dropped (dependencies only
 * link siblings) and so are its old siblings' dependencies on it; the rest of its JSON moves as written.
 */
export function moveActivity(text: string, from: Scope, name: string, to: Scope): EditResult {
  if (to.some(step => step.activity === name)) return { error: `'${name}' cannot move inside itself.` };
  if (sameScope(from, to)) return { text };
  return withPipeline(text, value => {
    const source = indexIn(value, from, name);
    const moving = asRecord(list(getAt(value, source.path))[source.index]);
    const loop = loopProblem(value, to, String(moving.type));
    if (loop) return { error: loop };
    if (containsLoop(moving) && loopProblem(value, to, "ForEach")) {
      return { error: `'${name}' holds a ForEach or Until, which cannot be nested in ForEach or Until.` };
    }
    // Cut the activity's own text, dependencies cleared.
    let fragment = text;
    if (Array.isArray(moving.dependsOn) && moving.dependsOn.length) fragment = replaceValue(fragment, [...source.path, source.index, "dependsOn"], []);
    const node = nodeAt(parseTree(fragment), [...source.path, source.index])!;
    const raw = fragment.slice(node.start, node.end);
    const rawIndent = lineIndent(fragment, node.start);
    let next = removeItem(text, source.path, source.index);
    next = pruneDependencies(next, source.path, new Set([name]));
    const after = JSON.parse(next) as Raw;
    const ensured = ensureScopeArray(next, after, to);
    return { text: insertRawItem(ensured.text, ensured.path, raw, rawIndent) };
  });
}

export function sameScope(a: Scope, b: Scope): boolean {
  return a.length === b.length && a.every((step, index) => step.activity === b[index].activity && step.key === b[index].key);
}

/** Set (or with `undefined`, remove) a property of an activity at a path relative to it, e.g. ["typeProperties", "items"]. */
export function setActivityProperty(text: string, scope: Scope, name: string, relative: JsonPath, propertyValue: unknown): EditResult {
  if (!relative.length) return { error: "Choose a property." };
  if (relative[0] === "name") return { error: "Rename the activity instead." };
  return withPipeline(text, value => {
    const { path, index } = indexIn(value, scope, name);
    const full = [...path, index, ...relative];
    return { text: propertyValue === undefined ? removePath(text, full) : setPath(text, full, propertyValue) };
  });
}

/** Add a case to a Switch. */
export function addSwitchCase(text: string, scope: Scope, name: string, caseValue: string): EditResult {
  if (!caseValue.trim()) return { error: "A case needs a value." };
  return withPipeline(text, value => {
    const { path, index } = indexIn(value, scope, name);
    const activity = asRecord(list(getAt(value, path))[index]);
    if (activity.type !== "Switch") return { error: `'${name}' is not a Switch.` };
    const cases = list(asRecord(activity.typeProperties).cases);
    if (cases.some(entry => String(asRecord(entry).value) === caseValue)) return { error: `The Switch already has a case '${caseValue}'.` };
    const entry = { value: caseValue, activities: [] };
    if (!Array.isArray(asRecord(activity.typeProperties).cases)) return { text: setPath(text, [...path, index, "typeProperties", "cases"], [entry]) };
    return { text: insertItem(text, [...path, index, "typeProperties", "cases"], entry) };
  });
}

// ---------------------------------------------------------------------------------------------------------------
// Undo / redo

export interface EditorHistory {
  past: readonly string[];
  present: string;
  future: readonly string[];
}

export function startHistory(text: string): EditorHistory {
  return { past: [], present: text, future: [] };
}

export function pushHistory(history: EditorHistory, text: string): EditorHistory {
  if (text === history.present) return history;
  return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: text, future: [] };
}

export function undo(history: EditorHistory): EditorHistory {
  if (!history.past.length) return history;
  return { past: history.past.slice(0, -1), present: history.past[history.past.length - 1], future: [history.present, ...history.future] };
}

export function redo(history: EditorHistory): EditorHistory {
  if (!history.future.length) return history;
  return { past: [...history.past, history.present].slice(-HISTORY_LIMIT), present: history.future[0], future: history.future.slice(1) };
}

// ---------------------------------------------------------------------------------------------------------------
// Validation (the editor's own checks; the runtime validates again when the pipeline runs)

export interface PipelineIssue {
  /** Activity path ("Loop/Copy table"), or "" for the pipeline. */
  path: string;
  message: string;
  severity: "error" | "warning";
}

export function validatePipeline(value: Raw, flavor: FactoryFlavor): PipelineIssue[] {
  const issues: PipelineIssue[] = [];
  const seen = new Map<string, string>();
  const error = (path: string, message: string) => issues.push({ path, message, severity: "error" });
  const rootActivities = getAt(value, rootActivitiesPath(value));
  if (!Array.isArray(rootActivities)) {
    error("", "No properties.activities array: is this a pipeline file?");
    return issues;
  }

  const container = (items: unknown, parent: string, loopDepth: number) => {
    const activities = list(items).map(asRecord);
    const names = new Set(activities.map(activity => String(activity.name)));
    for (const activity of activities) {
      const name = typeof activity.name === "string" ? activity.name : "";
      const path = parent ? `${parent}/${name}` : name;
      if (!name.trim()) { error(parent, "An activity has no name."); continue; }
      if (name.length > ACTIVITY_NAME_MAX || BAD_NAME.test(name)) {
        error(path, `Activity names are at most ${ACTIVITY_NAME_MAX} characters and cannot contain . + ? / < > * % & : \\`);
      }
      if (seen.has(name)) error(path, `Duplicate activity name '${name}' (also at ${seen.get(name)}): names are unique across the whole pipeline.`);
      seen.set(name, path);
      const type = String(activity.type ?? "");
      const spec = FACTORY_ACTIVITY_TYPES.find(item => item.name === type);
      if (!spec) {
        error(path, `Activity type '${type || "(none)"}' is not simulated for ${FACTORY_FLAVOR_LABELS[flavor]}: the run refuses it rather than guess what it does.`);
      } else if (!spec.flavors.includes(flavor)) {
        const hint = spec.equivalents[flavor];
        error(path, `'${type}' (${spec.label}) is not in ${FACTORY_FLAVOR_LABELS[flavor]}${hint ? `; use ${hint}` : ""}.`);
      }
      const props = asRecord(activity.typeProperties);
      for (const key of spec?.required ?? []) {
        if (!(key in props)) error(path, `${spec!.label} needs typeProperties.${key}.`);
      }
      for (const dependency of list(activity.dependsOn).map(asRecord)) {
        const other = dependency.activity;
        if (typeof other !== "string") { error(path, "A dependsOn entry has no activity name."); continue; }
        const conditions = Array.isArray(dependency.dependencyConditions) ? dependency.dependencyConditions : ["Succeeded"];
        const bad = conditions.filter(condition => !(DEPENDENCY_CONDITIONS as readonly unknown[]).includes(condition));
        if (bad.length || !conditions.length) {
          error(path, `Unknown dependency condition(s) ${bad.map(String).join(", ") || "(empty)"} on '${other}': use ${DEPENDENCY_CONDITIONS.join(", ")}.`);
        }
        if (other === name) error(path, "An activity cannot depend on itself.");
        else if (!names.has(other)) error(path, `Depends on '${other}', which is not an activity of the same level: dependencies only link siblings.`);
      }
      const loop = type === "ForEach" || type === "Until";
      if (loop && loopDepth > 0) error(path, `${type} cannot be nested in ForEach or Until; call a child pipeline for the inner loop.`);
      const inner = loopDepth + (loop ? 1 : 0);
      for (const key of FACTORY_CONTAINER_KEYS[type] ?? []) container(props[key], path, inner);
      if (type === "Switch") {
        list(props.cases).forEach((entry, index) => {
          const scase = asRecord(entry);
          if (!("value" in scase)) error(path, `cases[${index}] needs a value.`);
          else container(scase.activities, path, inner);
        });
      }
    }
    const cycle = cycleOf(activities);
    if (cycle.length) error(parent, `Dependency cycle between ${cycle.join(", ")}.`);
  };
  container(rootActivities, "", 0);

  // activity('X') in an expression must name an activity of the pipeline (a rename does not rewrite expressions).
  const known = new Set(seen.keys());
  const mentioned = new Set<string>();
  const scan = (node: unknown) => {
    if (typeof node === "string") {
      for (const match of node.matchAll(/activity\(\s*'((?:''|[^'])*)'\s*\)/g)) mentioned.add(match[1].replaceAll("''", "'"));
    } else if (Array.isArray(node)) node.forEach(scan);
    else if (node && typeof node === "object") Object.values(node).forEach(scan);
  };
  scan(rootActivities);
  for (const name of mentioned) {
    if (!known.has(name)) issues.push({ path: "", message: `An expression reads activity('${name}'), which is not an activity of this pipeline.`, severity: "warning" });
  }
  return issues;
}

/** Names left in a cycle after removing every activity whose dependencies can be ordered. */
function cycleOf(activities: readonly Raw[]): string[] {
  const names = new Set(activities.map(activity => String(activity.name)));
  const remaining = new Map(activities.map(activity => [String(activity.name),
    new Set(list(activity.dependsOn).map(d => String(asRecord(d).activity)).filter(other => names.has(other)))]));
  const done = new Set<string>();
  for (;;) {
    const ready = [...remaining].filter(([, deps]) => [...deps].every(dep => done.has(dep))).map(([name]) => name);
    if (!ready.length) break;
    for (const name of ready) { done.add(name); remaining.delete(name); }
  }
  return [...remaining.keys()].sort();
}

// ---------------------------------------------------------------------------------------------------------------
// Content hash (conflict detection between the editor's base and the file on disk)

/** A 53-bit string hash (cyrb53) plus the length: equal texts give equal hashes, the webview and the host agree. */
export function contentHash(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < text.length; index++) {
    const code = text.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return `${(4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16).padStart(14, "0")}-${text.length}`;
}
