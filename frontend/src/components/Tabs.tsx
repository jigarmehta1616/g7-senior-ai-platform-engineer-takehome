import type { TabsProps } from "../types/ui";

export function Tabs<Id extends string>({ tabs, active, onChange }: TabsProps<Id>) {
  return (
    <nav role="tablist" className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-4">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => {
            onChange(tab.id);
          }}
          className={`border-b-2 px-3 py-2.5 text-sm whitespace-nowrap ${
            active === tab.id ? "border-brand font-semibold text-ink" : "border-transparent text-muted hover:text-ink"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}
