import { useMutation, useQuery } from "@tanstack/react-query";

import { getInsightsOverview, queryInsights } from "../../lib/api/client";

export function useInsightsOverview(accessToken: string, month: string) {
  return useQuery({
    queryKey: ["insights-overview", accessToken, month],
    queryFn: ({ signal }) => getInsightsOverview(accessToken, month, signal),
  });
}

export function useInsightsDashboard(accessToken: string, month: string) {
  const overview = useInsightsOverview(accessToken, month);
  const query = useMutation({
    mutationFn: (question: string) =>
      queryInsights(accessToken, { month, question }),
  });
  return { overview, query };
}
