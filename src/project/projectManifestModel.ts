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
    /**
     * Request trusted local Python/Polars execution. Default false. Also requires
     * a per-machine confirmation and VS Code Workspace Trust; see platform/pythonTrust.
     */
    trustedLocalPython?: boolean;
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
  } else if (doc.runtime !== undefined) {
    const runtime = doc.runtime as Record<string, unknown>;
    if (runtime.storage !== undefined && runtime.storage !== "duckdb" && runtime.storage !== "ducklake") {
      issues.push('runtime.storage must be "duckdb" or "ducklake".');
    }
    if (runtime.pythonCommand !== undefined && (typeof runtime.pythonCommand !== "string" || !runtime.pythonCommand.trim())) {
      issues.push("runtime.pythonCommand must be a non-empty string.");
    }
    if (runtime.trustedLocalPython !== undefined && typeof runtime.trustedLocalPython !== "boolean") {
      issues.push("runtime.trustedLocalPython must be true or false.");
    }
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
      storage: "duckdb",
      pythonCommand: "python",
      trustedLocalPython: false
    }
  };
}

export function withTrustedLocalPython(
  manifest: DataPassProjectManifest,
  enabled: boolean
): DataPassProjectManifest {
  return {
    ...manifest,
    runtime: { ...manifest.runtime, trustedLocalPython: enabled }
  };
}

function slug(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "data-project";
}
