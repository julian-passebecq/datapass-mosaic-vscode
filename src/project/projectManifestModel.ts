export const DATAPASS_MANIFEST_PATH = ".datapass/project.json";

export interface DataPassProjectManifest {
  schemaVersion: 1;
  project: {
    id: string;
    title: string;
    description?: string;
  };
  assets?: {
    datasets?: string;
    lakehouse?: string;
    notebooks?: string;
    dbt?: string;
    pipelines?: string;
    airflow?: string;
    exercises?: string;
  };
  runtime?: {
    storage?: "ducklake" | "duckdb";
    pythonCommand?: string;
  };
}

export function validateProjectManifest(raw: unknown): string[] {
  const issues: string[] = [];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return ["Project manifest must be an object."];
  }

  const doc = raw as Record<string, unknown>;
  if (doc.schemaVersion !== 1) issues.push("schemaVersion must be 1.");

  if (!doc.project || typeof doc.project !== "object" || Array.isArray(doc.project)) {
    issues.push("project is required.");
  } else {
    const project = doc.project as Record<string, unknown>;
    if (typeof project.id !== "string" || !project.id.trim()) {
      issues.push("project.id is required.");
    }
    if (typeof project.title !== "string" || !project.title.trim()) {
      issues.push("project.title is required.");
    }
  }

  if (doc.assets !== undefined && (!doc.assets || typeof doc.assets !== "object" || Array.isArray(doc.assets))) {
    issues.push("assets must be an object.");
  }
  if (doc.runtime !== undefined && (!doc.runtime || typeof doc.runtime !== "object" || Array.isArray(doc.runtime))) {
    issues.push("runtime must be an object.");
  }

  return issues;
}

export function createDefaultProjectManifest(folderName = "data-project"): DataPassProjectManifest {
  return {
    schemaVersion: 1,
    project: {
      id: slug(folderName),
      title: folderName
    },
    assets: {
      datasets: "datasets",
      lakehouse: "lakehouse",
      notebooks: "notebooks",
      dbt: "dbt",
      pipelines: "pipelines",
      airflow: "airflow",
      exercises: "exercises"
    },
    runtime: {
      storage: "ducklake",
      pythonCommand: "python"
    }
  };
}

function slug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "data-project";
}
