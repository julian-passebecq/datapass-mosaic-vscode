/**
 * A manifest asset folder (`assets.datasets`, `assets.pipelines`, ...) as path parts under the workspace root. Absolute
 * paths, drive letters, `.` and `..` are refused: the fallback folder is used instead.
 */
export function safeRelativeParts(value: string | undefined, fallback: string): string[] {
  const normalized = (value ?? fallback).replaceAll("\\", "/");
  const parts = normalized.split("/").filter(Boolean);
  if (
    parts.length === 0 ||
    parts.some(part => part === "." || part === ".." || part.includes(":"))
  ) {
    return [fallback];
  }
  return parts;
}
