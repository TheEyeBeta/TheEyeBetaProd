import { statusTone } from "../api/normalizers";

export function StatusDot({
  status,
  pulse = false
}: {
  status?: string | boolean;
  pulse?: boolean;
}) {
  const tone = statusTone(status);
  const color =
    tone === "ok"
      ? "bg-terminal-positive"
      : tone === "warn"
        ? "bg-terminal-secondary"
        : tone === "bad"
          ? "bg-terminal-danger"
          : "bg-terminal-muted";
  return (
    <span
      className={`inline-block h-2 w-2 ${color} ${pulse ? "animate-pulse shadow-neon" : ""}`}
      aria-label={String(status ?? "unknown")}
    />
  );
}
