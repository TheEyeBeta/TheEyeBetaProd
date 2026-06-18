import { EmptyState } from "../components/EmptyState";
import { Panel } from "../components/Panel";

export function PlaceholderPanel({ title }: { title: string }) {
  return (
    <Panel title={title} className="h-full">
      <EmptyState label={`${title} panel queued for implementation`} />
    </Panel>
  );
}
