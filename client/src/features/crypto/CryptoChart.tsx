import {
  ColorType,
  createChart,
  LineSeries,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { CryptoOverview } from "../../lib/api/client";

type Asset = "BTC" | "ETH" | "SOL";

export function CryptoChart({
  overview,
  asset,
}: {
  overview: CryptoOverview;
  asset: Asset;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (container.current === null || overview.forecast === null) return;
    const host = container.current;
    const chart: IChartApi = createChart(host, {
      width: host.clientWidth,
      height: 310,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#73809a",
      },
      grid: {
        vertLines: { color: "rgba(115, 128, 154, 0.12)" },
        horzLines: { color: "rgba(115, 128, 154, 0.12)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
    });
    const historical = overview.forecast.price_history
      .filter((point) => point.asset === asset)
      .map((point) => ({
        time: point.observed_at_utc.slice(0, 10) as Time,
        value: Number(point.price_usd),
      }));
    const forecast = overview.forecast.forecasts.find(
      (item) => item.asset === asset,
    );
    if (historical.length > 0 && forecast !== undefined) {
      const historyLine = chart.addSeries(LineSeries, {
        color: "#6555a5",
        lineWidth: 3,
        title: `${asset} observed`,
      });
      historyLine.setData(historical);
      const last = historical.at(-1)!;
      const horizon = new Date(overview.forecast.as_of_utc);
      horizon.setUTCDate(horizon.getUTCDate() + overview.forecast.horizon_days);
      const horizonTime = horizon.toISOString().slice(0, 10) as Time;
      const overlays = [
        ["p10_return", "#d16d7f", "P10"],
        ["p50_return", "#2c9c91", "P50"],
        ["p90_return", "#d49735", "P90"],
      ] as const;
      overlays.forEach(([field, color, title]) => {
        const line = chart.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          lineStyle: 2,
          title,
        });
        const points: LineData[] = [
          last,
          {
            time: horizonTime,
            value: last.value * (1 + Number(forecast[field])),
          },
        ];
        line.setData(points);
      });
      chart.timeScale().fitContent();
    }
    const resize = new ResizeObserver(() => {
      chart.applyOptions({ width: host.clientWidth });
    });
    resize.observe(host);
    return () => {
      resize.disconnect();
      chart.remove();
    };
  }, [asset, overview]);

  return (
    <div
      className="crypto-chart"
      ref={container}
      role="img"
      aria-label={`${asset} historical USD prices with 15-day P10, P50, and P90 forecast overlays`}
    />
  );
}
