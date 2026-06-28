import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export type SparkPoint = {
  x: string;
  y: number;
};

export function Sparkline({ data, color = "#00FFD1" }: { data: SparkPoint[]; color?: string }) {
  if (data.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs uppercase text-terminal-muted">
        No series data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <XAxis dataKey="x" hide />
        <YAxis hide domain={["dataMin", "dataMax"]} />
        <Tooltip
          contentStyle={{
            background: "#0D0D15",
            border: "1px solid #1A1A2E",
            borderRadius: 0,
            color: "#E8E8F0",
            fontSize: 11
          }}
          labelStyle={{ color: "#6B7280" }}
        />
        <Line
          type="monotone"
          dataKey="y"
          stroke={color}
          dot={false}
          strokeWidth={2}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
