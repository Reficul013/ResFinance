import {
  formatIntentTimestamp,
  hashParameters,
  signIntent,
  type JsonValue,
  type SignedIntent,
} from "../auth/reswallet";
import { usdToMinorUnits } from "../finance/money";
import type { GroupActionSteps } from "./useGroupAction";
import type { useGroupsDashboard } from "./useGroupsDashboard";

export type Dashboard = ReturnType<typeof useGroupsDashboard>;
export type GroupOverview = NonNullable<Dashboard["overview"]["data"]>;
export type GroupObligation = GroupOverview["obligations"][number];
export type GroupExpense = GroupOverview["expenses"][number];

type ContractAction = "split.approve" | "credits.fund" | "settlement.authorize";

export function isGroupWritePending(dashboard: Dashboard): boolean {
  return (
    dashboard.member.isPending ||
    dashboard.expense.isPending ||
    dashboard.decision.isPending ||
    dashboard.credits.isPending ||
    dashboard.settlement.isPending
  );
}

export async function requestSignature(
  action: ContractAction,
  resourceId: string,
  parameters: Record<string, JsonValue>,
): Promise<SignedIntent & { action: ContractAction }> {
  const issuedAt = new Date();
  const signed = await signIntent({
    version: 1,
    intent_id: crypto.randomUUID(),
    action,
    resource_id: resourceId,
    parameters,
    parameters_hash: await hashParameters(parameters),
    nonce: crypto.randomUUID(),
    issued_at: formatIntentTimestamp(issuedAt),
    expires_at: formatIntentTimestamp(
      new Date(issuedAt.getTime() + 5 * 60 * 1000),
    ),
    origin: window.location.origin,
    audience: "resfinance-api",
    network_id: "pinned-local-network",
  });
  if (signed.action !== action)
    throw new Error("ResWallet signed another action");
  return { ...signed, action };
}

export async function decideObligation(
  dashboard: Dashboard,
  group: GroupOverview,
  obligationId: string,
  decision: "approve" | "reject",
  { sign }: GroupActionSteps,
) {
  const parameters = {
    group_id: group.group_id,
    obligation_id: obligationId,
    decision,
    expected_version: group.provenance.projection_version,
  };
  const intent = await sign(
    requestSignature("split.approve", obligationId, parameters),
  );
  await dashboard.decision.mutateAsync({
    groupId: group.group_id,
    obligationId,
    idempotencyKey: `decision-${intent.intent_id}`,
    body: {
      decision,
      expected_version: group.provenance.projection_version,
      intent,
    },
  });
}

export async function settleObligation(
  dashboard: Dashboard,
  group: GroupOverview,
  obligationId: string,
  amount: string,
  { sign }: GroupActionSteps,
) {
  const amountMinorUnits = usdToMinorUnits(amount);
  const parameters = {
    group_id: group.group_id,
    obligation_id: obligationId,
    amount_minor_units: amountMinorUnits,
    expected_version: group.provenance.projection_version,
  };
  const intent = await sign(
    requestSignature("settlement.authorize", obligationId, parameters),
  );
  await dashboard.settlement.mutateAsync({
    groupId: group.group_id,
    obligationId,
    idempotencyKey: `settlement-${intent.intent_id}`,
    body: {
      amount: { currency: "USD", minor_units: amountMinorUnits },
      expected_version: group.provenance.projection_version,
      intent,
    },
  });
}
