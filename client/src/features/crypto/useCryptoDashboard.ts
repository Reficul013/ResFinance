import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  analyzePortfolioScenario,
  getCryptoOverview,
  recordRiskProfile,
  type RiskProfileCommand,
  type ScenarioCommand,
} from "../../lib/api/client";

export function useCryptoDashboard(accessToken: string, month: string) {
  const queryClient = useQueryClient();
  const queryKey = ["crypto-overview", accessToken, month] as const;
  const overview = useQuery({
    queryKey,
    queryFn: ({ signal }) => getCryptoOverview(accessToken, month, signal),
  });
  const riskProfile = useMutation({
    mutationFn: ({
      body,
      idempotencyKey,
    }: {
      body: RiskProfileCommand;
      idempotencyKey: string;
    }) => recordRiskProfile(accessToken, idempotencyKey, body),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey }),
  });
  const scenario = useMutation({
    mutationFn: (body: ScenarioCommand) =>
      analyzePortfolioScenario(accessToken, body),
  });
  return { overview, riskProfile, scenario };
}
