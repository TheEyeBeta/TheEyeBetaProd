import { EmptyState } from "./EmptyState";

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  className?: string;
};

export function DataTable<T>({
  rows,
  columns,
  empty,
  getKey
}: {
  rows: T[];
  columns: Column<T>[];
  empty: string;
  getKey: (row: T, index: number) => string;
}) {
  if (rows.length === 0) return <EmptyState label={empty} />;
  return (
    <table className="w-full border-collapse text-left text-xs">
      <thead className="sticky top-0 bg-terminal-panel text-terminal-muted">
        <tr>
          {columns.map((column) => (
            <th
              key={column.key}
              className={`border-b border-terminal-border px-2 py-1 font-medium ${column.className ?? ""}`}
            >
              {column.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="font-mono text-terminal-text">
        {rows.map((row, index) => (
          <tr key={getKey(row, index)} className="hover:bg-terminal-panel2">
            {columns.map((column) => (
              <td
                key={column.key}
                className={`border-b border-terminal-border px-2 py-1 ${column.className ?? ""}`}
              >
                {column.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
