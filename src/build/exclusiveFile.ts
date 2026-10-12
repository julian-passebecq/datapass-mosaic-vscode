import { mkdir, writeFile } from "node:fs/promises";
import * as path from "node:path";

/**
 * Create a file only when it does not exist yet (`wx`): a file that exists, even one created a moment ago by another
 * writer, is never replaced. Returns false when it already existed. No vscode: shared with the node tests.
 */
export async function createExclusiveAt(fsPath: string, content: string | Uint8Array): Promise<boolean> {
  await mkdir(path.dirname(fsPath), { recursive: true });
  try {
    await writeFile(fsPath, content, { flag: "wx" });
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  }
}
