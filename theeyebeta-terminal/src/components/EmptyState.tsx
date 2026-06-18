export function EmptyState({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-24 items-center justify-center border border-dashed border-terminal-border bg-terminal-panel2 px-4 text-center text-xs uppercase tracking-wide text-terminal-muted">
      {label}
    </div>
  );
}
