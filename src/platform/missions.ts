/**
 * Missions (dbt Lab and Terminal Lab; the Infra Lab will reuse them): what the Workbench shows of a mission, the
 * learner's progress, and the hidden checker's answer. Pure (no vscode import) for scripts/missions_ui_smoke.mjs.
 *
 * The runtime owns the contract (runtime/missionlab/model.py) and the checker; the extension only reads what it
 * shows, tolerantly, from content/missions/<pack>/<mission>/mission.json.
 */

export interface MissionTicketView {
  from: string;
  subject: string;
  body: string;
}

export interface MissionView {
  id: string;
  version: string;
  lab: string;
  packId: string;
  title: string;
  level: string;
  estimate: string;
  skills: string[];
  ticket: MissionTicketView;
  acceptance: { id: string; text: string }[];
  hints: string[];
  batches: { id: string; label: string }[];
  /** Boards whose `dct validate` result the checker needs (the host runs the real dct for them). */
  dctBoards: string[];
}

export interface MissionCheckView {
  status: "passed" | "not-yet";
  requires: string[];
  criteria: { id: string; text: string; passed: boolean; details: string[] }[];
  checkedAt: string;
  truth: string;
  version?: string;
}

export interface MissionProgressView {
  started?: string;
  /** Batch ids loaded since the last (re)start, in order. */
  batches: string[];
  hintsShown: number;
  lastCheck?: MissionCheckView;
  passedAt?: string;
}

export interface MissionsProgressFile {
  version: 1;
  missions: Record<string, MissionProgressView>;
}

const ID = /^[a-z0-9][a-z0-9-]{0,47}$/;

export function missionFolder(id: string): string {
  if (!ID.test(id)) throw new Error(`Invalid mission id ${id}.`);
  return `missions/${id}`;
}

/**
 * Where the ticket is written, relative to the workspace. dbt Lab: TICKET.md in the project folder, next to the code.
 * Terminal Lab: outside the mission folder, because the mission is about that folder's exact content and its Git
 * status (a TICKET.md in it would be an untracked file the learner did not make).
 */
export function ticketPath(mission: Pick<MissionView, "id" | "lab">): string {
  const folder = missionFolder(mission.id);
  return mission.lab === "terminal" ? `.datapass/missions/tickets/${mission.id}.md` : `${folder}/TICKET.md`;
}

export function toMissionView(raw: unknown, packId: string): MissionView | undefined {
  const mission = record(raw);
  if (!mission || typeof mission.id !== "string" || !ID.test(mission.id) || typeof mission.title !== "string") return undefined;
  const ticket = record(mission.ticket) ?? {};
  const acceptance = array(mission.acceptance).flatMap(item => {
    const criterion = record(item);
    return criterion && typeof criterion.id === "string" && typeof criterion.text === "string" ? [{ id: criterion.id, text: criterion.text }] : [];
  });
  const dctBoards = array(mission.acceptance).flatMap(item => array(record(item)?.checks))
    .flatMap(check => { const c = record(check); return c?.kind === "dct_validate" && typeof c.board === "string" ? [c.board] : []; });
  return {
    id: mission.id,
    version: str(mission.version, "1"),
    lab: str(mission.lab, "dbt"),
    packId,
    title: mission.title,
    level: str(mission.level, "intermediate"),
    estimate: str(mission.estimate, ""),
    skills: array(mission.skills).filter((skill): skill is string => typeof skill === "string"),
    ticket: { from: str(ticket.from, "the team"), subject: str(ticket.subject, mission.title), body: lines(ticket.body) },
    acceptance,
    hints: array(mission.hints).filter((hint): hint is string => typeof hint === "string"),
    batches: array(mission.batches).flatMap(item => {
      const batch = record(item);
      return batch && typeof batch.id === "string" ? [{ id: batch.id, label: str(batch.label, batch.id) }] : [];
    }),
    dctBoards: [...new Set(dctBoards)]
  };
}

/** The checker's answer: the runtime's shape (checks, checked_at) or the stored one (details, checkedAt). */
export function toMissionCheckView(raw: unknown): MissionCheckView {
  const result = record(raw);
  if (!result || !Array.isArray(result.criteria)) throw new Error("The runtime returned no mission check.");
  return {
    status: result.status === "passed" ? "passed" : "not-yet",
    requires: array(result.requires).filter((item): item is string => typeof item === "string"),
    criteria: result.criteria.flatMap(item => {
      const criterion = record(item);
      if (!criterion || typeof criterion.id !== "string") return [];
      const checks = array(criterion.checks).map(record).filter((c): c is Record<string, unknown> => Boolean(c));
      const details = Array.isArray(criterion.details)
        ? criterion.details.filter((detail): detail is string => typeof detail === "string")
        : checks.filter(check => check.passed !== true).map(check => str(check.detail, "Not met."));
      return [{ id: criterion.id, text: str(criterion.text, criterion.id), passed: criterion.passed === true, details }];
    }),
    checkedAt: str(result.checked_at, str(result.checkedAt, new Date().toISOString())),
    truth: str(result.truth, ""),
    version: typeof result.version === "string" ? result.version : undefined
  };
}

export function emptyProgress(): MissionsProgressFile {
  return { version: 1, missions: {} };
}

/** Read `.datapass/missions/progress.json` tolerantly: anything unexpected is dropped, never trusted. */
export function toProgressFile(raw: unknown): MissionsProgressFile {
  const file = record(raw);
  const out = emptyProgress();
  for (const [id, value] of Object.entries(record(file?.missions) ?? {})) {
    const progress = record(value);
    if (!ID.test(id) || !progress) continue;
    let lastCheck: MissionCheckView | undefined;
    try {
      lastCheck = progress.lastCheck ? toMissionCheckView(progress.lastCheck) : undefined;
    } catch {
      lastCheck = undefined;
    }
    out.missions[id] = {
      started: typeof progress.started === "string" ? progress.started : undefined,
      batches: array(progress.batches).filter((b): b is string => typeof b === "string").slice(0, 10),
      hintsShown: typeof progress.hintsShown === "number" && progress.hintsShown >= 0 ? Math.floor(progress.hintsShown) : 0,
      lastCheck,
      passedAt: typeof progress.passedAt === "string" ? progress.passedAt : undefined
    };
  }
  return out;
}

/** The next batch to load, or undefined when every batch is in. */
export function nextBatch(mission: MissionView, progress: MissionProgressView | undefined): { id: string; label: string } | undefined {
  if (!progress?.started) return undefined;
  return mission.batches.find(batch => !progress.batches.includes(batch.id));
}

export type MissionStatus = "new" | "in-progress" | "passed";

export function missionStatus(progress: MissionProgressView | undefined): MissionStatus {
  if (progress?.passedAt) return "passed";
  return progress?.started ? "in-progress" : "new";
}

/** TICKET.md written into the mission folder, so the brief sits next to the code in VS Code. */
export function ticketMarkdown(mission: MissionView): string {
  const criteria = mission.acceptance.map(item => `- [ ] ${item.text}`).join("\n");
  return [
    `# ${mission.ticket.subject}`,
    "",
    `From: ${mission.ticket.from} · Mission \`${mission.id}\` (${mission.level}${mission.estimate ? `, ${mission.estimate}` : ""})`,
    "",
    mission.ticket.body,
    "",
    "## Acceptance criteria",
    "",
    criteria,
    "",
    ...(mission.lab === "terminal"
      ? [
        `Work in \`${missionFolder(mission.id)}/\` with your own commands (the Terminal Lab opens a terminal there). Check`,
        "your work from the Terminal Lab: a hidden checker reads the folder and its Git repository. Datapass runs none",
        "of your commands and never runs your scripts. Hints are there too, one at a time."
      ]
      : [
        "Check your work from the dbt Lab's Missions tab: a hidden checker looks at your catalog, your dbt artifacts and",
        "your files. Hints are there too, one at a time."
      ]),
    ""
  ].join("\n");
}

/**
 * A small, safe reading of the ticket's Markdown for the webview: paragraphs, bullet lists, fenced code, and inline
 * `code` / **bold**. Returned as data, rendered as React elements (never as HTML).
 */
export type TicketBlock =
  | { kind: "p"; spans: TicketSpan[] }
  | { kind: "ul" | "ol"; items: TicketSpan[][] }
  | { kind: "code"; text: string };
export type TicketSpan = { kind: "text" | "code" | "strong"; text: string };

export function ticketBlocks(markdown: string): TicketBlock[] {
  const blocks: TicketBlock[] = [];
  const lines = markdown.replaceAll("\r\n", "\n").split("\n");
  let paragraph: string[] = [];
  let list: { kind: "ul" | "ol"; items: string[] } | undefined;
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "p", spans: spans(paragraph.join(" ")) });
    paragraph = [];
    if (list) blocks.push({ kind: list.kind, items: list.items.map(spans) });
    list = undefined;
  };
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      flush();
      const code: string[] = [];
      for (index++; index < lines.length && !lines[index].trim().startsWith("```"); index++) code.push(lines[index]);
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      if (paragraph.length || (list && list.kind !== kind)) flush();
      list ??= { kind, items: [] };
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
      continue;
    }
    if (list) flush();
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

function spans(text: string): TicketSpan[] {
  const out: TicketSpan[] = [];
  const pattern = /`([^`]+)`|\*\*([^*]+)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push({ kind: "text", text: text.slice(last, match.index) });
    out.push(match[1] !== undefined ? { kind: "code", text: match[1] } : { kind: "strong", text: match[2] });
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

function lines(value: unknown): string {
  if (Array.isArray(value)) return value.filter((line): line is string => typeof line === "string").join("\n");
  return typeof value === "string" ? value : "";
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function str(value: unknown, fallback: string): string {
  return typeof value === "string" && value ? value : fallback;
}
