import type { DataTableProps } from "../types/ui";

/** Generic table: pass typed column definitions and rows. Rows become keyboard-clickable when `onRowClick` is set. */
export function DataTable<T>({ columns, rows, rowKey, onRowClick, empty = "Nothing to show." }: DataTableProps<T>) {
  const clickable = onRowClick !== undefined;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            {columns.map((col) => (
              <th key={col.header} scope="col" className="px-3 py-2 font-semibold whitespace-nowrap">
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              tabIndex={clickable ? 0 : undefined}
              onClick={clickable ? () => { onRowClick(row); } : undefined}
              onKeyDown={clickable ? (e) => { if (e.key === "Enter") onRowClick(row); } : undefined}
              className={`border-b border-line last:border-0 ${clickable ? "cursor-pointer hover:bg-canvas focus:bg-canvas focus:outline-none" : ""}`}
            >
              {columns.map((col) => (
                <td key={col.header} className={`px-3 py-2 ${col.className ?? "whitespace-nowrap"}`}>
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="p-4 text-sm text-muted">{empty}</p>}
    </div>
  );
}
