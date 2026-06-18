export function ActionButton({
  children,
  variant = "primary",
  disabled = false,
  onClick,
  type = "button"
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  const color =
    variant === "danger"
      ? "border-terminal-danger text-terminal-danger"
      : variant === "secondary"
        ? "border-terminal-secondary text-terminal-secondary"
        : "border-terminal-primary text-terminal-primary";
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`h-7 border bg-terminal-bg px-2 text-xs font-semibold uppercase tracking-wide ${color} ${
        disabled ? "cursor-not-allowed opacity-40" : "hover:shadow-neon"
      }`}
    >
      {children}
    </button>
  );
}
