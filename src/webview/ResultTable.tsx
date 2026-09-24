import type { LocalCellRunView } from "./contracts";

export function ResultTable({
  result,
  maxRows = 8
}: {
  result: NonNullable<LocalCellRunView["result"]>;
  maxRows?: number;
}) {
  if (result.columns.length === 0) {
    return <div className="muted">No tabular result.</div>;
  }
  return (
    <div className="retail-preview-wrap">
      <table className="retail-preview">
        <thead>
          <tr>{result.columns.map(column => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {result.rows.slice(0, maxRows).map((row, index) => (
            <tr key={index}>
              {result.columns.map(column => (
                <td key={column}>{String(row[column] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
