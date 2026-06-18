export function Panel({
  title,
  action,
  children,
  className = ""
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`flex min-h-0 flex-col border border-terminal-border bg-terminal-panel ${className}`}
    >
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-terminal-border px-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-terminal-primary">
          {title}
        </h2>
        {action ? <div className="text-xs text-terminal-muted">{action}</div> : null}
      </header>
      <div className="min-h-0 flex-1 overflow-auto p-2">{children}</div>
    </section>
  );
}
