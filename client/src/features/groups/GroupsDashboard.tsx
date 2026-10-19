import { useEffect, useMemo, useState } from "react";

import {
  formatIntentTimestamp,
  hashParameters,
  signIntent,
  type JsonValue,
  type SignedIntent,
} from "../auth/resvault";
import { formatUsd, usdToMinorUnits } from "../finance/money";
import { useGroupsDashboard } from "./useGroupsDashboard";

interface Props {
  accessToken: string;
  actorAddress: string;
}

export function GroupsDashboard({ accessToken, actorAddress }: Props) {
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const dashboard = useGroupsDashboard(accessToken, selectedGroupId);

  useEffect(() => {
    if (
      selectedGroupId === null &&
      dashboard.groups.data !== undefined &&
      dashboard.groups.data.length > 0
    ) {
      setSelectedGroupId(dashboard.groups.data[0]!.group_id);
    }
  }, [dashboard.groups.data, selectedGroupId]);

  return (
    <div className="dashboard groups-dashboard">
      <header className="dashboard-header">
        <div>
          <p className="eyebrow">Friends &amp; Groups</p>
          <h1>Shared expenses, signed by every participant.</h1>
          <p className="lede">
            ResContract is authoritative for obligations and settlements.
            Finance changes only after an immutable contract receipt is
            confirmed.
          </p>
        </div>
        <span className="provenance-chip">
          Wallet {shortAddress(actorAddress)}
        </span>
      </header>

      <CreateGroupPanel
        pending={dashboard.create.isPending}
        error={dashboard.create.error}
        onCreate={async (name, displayName) => {
          const groupId = `group-${crypto.randomUUID()}`;
          await dashboard.create.mutateAsync({
            idempotencyKey: `create-${groupId}`,
            body: {
              group_id: groupId,
              name,
              owner_display_name: displayName,
              expected_version: 0,
            },
          });
          setSelectedGroupId(groupId);
        }}
      />

      {dashboard.groups.isLoading && (
        <DashboardState text="Loading your groups…" />
      )}
      {dashboard.groups.isError && (
        <DashboardState text={errorMessage(dashboard.groups.error)} error />
      )}
      {dashboard.groups.data !== undefined &&
        dashboard.groups.data.length > 0 && (
          <nav className="group-switcher" aria-label="Your groups">
            {dashboard.groups.data.map((group) => (
              <button
                key={group.group_id}
                className={group.group_id === selectedGroupId ? "active" : ""}
                onClick={() => setSelectedGroupId(group.group_id)}
              >
                <strong>{group.name}</strong>
                <span>
                  {group.member_count} members · {group.open_obligation_count}{" "}
                  open
                </span>
              </button>
            ))}
          </nav>
        )}

      {selectedGroupId !== null && dashboard.overview.isLoading && (
        <DashboardState text="Rebuilding the group projection…" />
      )}
      {dashboard.overview.isError && (
        <DashboardState text={errorMessage(dashboard.overview.error)} error />
      )}
      {dashboard.overview.data !== undefined && (
        <GroupWorkspace
          actorAddress={actorAddress}
          group={dashboard.overview.data}
          dashboard={dashboard}
        />
      )}
    </div>
  );
}

type Dashboard = ReturnType<typeof useGroupsDashboard>;
type GroupOverview = NonNullable<Dashboard["overview"]["data"]>;

function GroupWorkspace({
  actorAddress,
  group,
  dashboard,
}: {
  actorAddress: string;
  group: GroupOverview;
  dashboard: Dashboard;
}) {
  return (
    <>
      <section className="group-overview panel">
        <div>
          <p className="eyebrow">Active group</p>
          <h2>{group.name}</h2>
          <p>{group.credit_disclaimer}</p>
        </div>
        <dl className="group-metrics">
          <div>
            <dt>Members</dt>
            <dd>{group.members.length}</dd>
          </div>
          <div>
            <dt>Your credits</dt>
            <dd>
              {formatUsd(group.credit_balances[actorAddress]?.minor_units ?? 0)}
            </dd>
          </div>
          <div>
            <dt>Projection</dt>
            <dd>v{group.provenance.projection_version}</dd>
          </div>
        </dl>
      </section>

      <div className="group-actions-grid">
        {group.owner_address === actorAddress && (
          <AddMemberPanel group={group} dashboard={dashboard} />
        )}
        <FundCreditsPanel
          actorAddress={actorAddress}
          group={group}
          dashboard={dashboard}
        />
        <CreateExpensePanel
          actorAddress={actorAddress}
          group={group}
          dashboard={dashboard}
        />
      </div>

      <ObligationsPanel
        actorAddress={actorAddress}
        group={group}
        dashboard={dashboard}
      />
      <NotificationsPanel actorAddress={actorAddress} group={group} />
      <footer className="provenance-footer">
        <span>Projection v{group.provenance.projection_version}</span>
        <span>
          {group.provenance.source_event_ids.length} encrypted source events
        </span>
        <span>{formatTimestamp(group.provenance.as_of_utc)}</span>
      </footer>
    </>
  );
}

function CreateGroupPanel({
  pending,
  error,
  onCreate,
}: {
  pending: boolean;
  error: Error | null;
  onCreate(name: string, displayName: string): Promise<void>;
}) {
  const [name, setName] = useState("");
  const [displayName, setDisplayName] = useState("");
  return (
    <section className="panel compact-form">
      <div>
        <p className="eyebrow">New group</p>
        <h2>Create a shared ledger</h2>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void onCreate(name, displayName).then(() => {
            setName("");
            setDisplayName("");
          });
        }}
      >
        <label>
          Group name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <label>
          Your display name
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            required
          />
        </label>
        <button disabled={pending}>
          {pending ? "Creating…" : "Create group"}
        </button>
      </form>
      <MutationError error={error} />
    </section>
  );
}

function AddMemberPanel({
  group,
  dashboard,
}: {
  group: GroupOverview;
  dashboard: Dashboard;
}) {
  const [address, setAddress] = useState("");
  const [name, setName] = useState("");
  return (
    <section className="panel compact-form">
      <h2>Add member</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const id = crypto.randomUUID();
          void dashboard.member
            .mutateAsync({
              groupId: group.group_id,
              idempotencyKey: `member-${id}`,
              body: {
                member_address: address,
                display_name: name,
                expected_version: group.provenance.projection_version,
              },
            })
            .then(() => {
              setAddress("");
              setName("");
            });
        }}
      >
        <label>
          Wallet address
          <input
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            pattern="0x[0-9a-fA-F]{40}"
            required
          />
        </label>
        <label>
          Display name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <button disabled={isGroupWritePending(dashboard)}>Add member</button>
      </form>
      <MutationError error={dashboard.member.error} />
    </section>
  );
}

function FundCreditsPanel({
  actorAddress,
  group,
  dashboard,
}: {
  actorAddress: string;
  group: GroupOverview;
  dashboard: Dashboard;
}) {
  const [amount, setAmount] = useState("");
  return (
    <section className="panel compact-form">
      <h2>Fund internal credits</h2>
      <p className="form-note">
        Non-redeemable ledger credits only; no fiat or crypto moves.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void (async () => {
            const amountMinorUnits = usdToMinorUnits(amount);
            const parameters = {
              group_id: group.group_id,
              amount_minor_units: amountMinorUnits,
              expected_version: group.provenance.projection_version,
            };
            const intent = await requestSignature(
              "credits.fund",
              group.group_id,
              parameters,
            );
            await dashboard.credits.mutateAsync({
              groupId: group.group_id,
              idempotencyKey: `credits-${intent.intent_id}`,
              body: {
                amount: { currency: "USD", minor_units: amountMinorUnits },
                expected_version: group.provenance.projection_version,
                intent,
              },
            });
            setAmount("");
          })();
        }}
      >
        <label>
          Credit amount (USD units)
          <input
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            placeholder="60.00"
            required
          />
        </label>
        <button disabled={isGroupWritePending(dashboard)}>
          Approve funding in ResVault
        </button>
      </form>
      <p className="form-note">Funding wallet: {shortAddress(actorAddress)}</p>
      <MutationError error={dashboard.credits.error} />
    </section>
  );
}

function CreateExpensePanel({
  actorAddress,
  group,
  dashboard,
}: {
  actorAddress: string;
  group: GroupOverview;
  dashboard: Dashboard;
}) {
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [occurredOn, setOccurredOn] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const [dueOn, setDueOn] = useState("");
  const [sharesText, setSharesText] = useState("");
  const memberHint = useMemo(
    () => group.members.map((item) => `${item.actor_address}=0.00`).join("\n"),
    [group.members],
  );
  return (
    <section className="panel expense-form">
      <h2>Create signed expense</h2>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void (async () => {
            const expenseId = `expense-${crypto.randomUUID()}`;
            const amountMinorUnits = usdToMinorUnits(amount);
            const shares = parseShares(sharesText);
            const parameters: Record<string, JsonValue> = {
              group_id: group.group_id,
              expense_id: expenseId,
              payer_address: actorAddress,
              description,
              amount_minor_units: amountMinorUnits,
              occurred_on: occurredOn,
              due_on: dueOn || null,
              shares: Object.fromEntries(
                Object.entries(shares).sort(([left], [right]) =>
                  left.localeCompare(right),
                ),
              ),
              expected_version: group.provenance.projection_version,
            };
            const intent = await requestSignature(
              "split.approve",
              expenseId,
              parameters,
            );
            await dashboard.expense.mutateAsync({
              groupId: group.group_id,
              idempotencyKey: `expense-${intent.intent_id}`,
              body: {
                expense_id: expenseId,
                payer_address: actorAddress,
                description,
                amount: { currency: "USD", minor_units: amountMinorUnits },
                occurred_on: occurredOn,
                due_on: dueOn || null,
                shares: Object.fromEntries(
                  Object.entries(shares).map(([address, minor_units]) => [
                    address,
                    { currency: "USD" as const, minor_units },
                  ]),
                ),
                expected_version: group.provenance.projection_version,
                intent,
              },
            });
            setDescription("");
            setAmount("");
            setSharesText("");
          })();
        }}
      >
        <label>
          Description
          <input
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            required
          />
        </label>
        <label>
          Total amount
          <input
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            inputMode="decimal"
            required
          />
        </label>
        <label>
          Expense date
          <input
            type="date"
            value={occurredOn}
            onChange={(event) => setOccurredOn(event.target.value)}
            required
          />
        </label>
        <label>
          Due date
          <input
            type="date"
            value={dueOn}
            onChange={(event) => setDueOn(event.target.value)}
          />
        </label>
        <label className="wide-field">
          Exact shares, one wallet=amount per line
          <textarea
            value={sharesText}
            onChange={(event) => setSharesText(event.target.value)}
            placeholder={memberHint}
            rows={Math.max(group.members.length, 3)}
            required
          />
        </label>
        <button disabled={isGroupWritePending(dashboard)}>
          Approve split in ResVault
        </button>
      </form>
      <MutationError error={dashboard.expense.error} />
    </section>
  );
}

function ObligationsPanel({
  actorAddress,
  group,
  dashboard,
}: {
  actorAddress: string;
  group: GroupOverview;
  dashboard: Dashboard;
}) {
  const [settlements, setSettlements] = useState<Record<string, string>>({});
  return (
    <section
      className="panel obligations-panel"
      aria-labelledby="obligations-title"
    >
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Contract state</p>
          <h2 id="obligations-title">Obligations</h2>
        </div>
        <span className="provenance-chip">
          {group.obligations.length} total
        </span>
      </div>
      {group.obligations.length === 0 ? (
        <p className="empty-copy">
          No obligations yet. Create a shared expense to begin.
        </p>
      ) : (
        <div className="obligation-list">
          {group.obligations.map((obligation) => {
            const isDebtor = obligation.debtor_address === actorAddress;
            const maySettle =
              isDebtor &&
              ["open", "partially_settled"].includes(obligation.status);
            return (
              <article
                key={obligation.obligation_id}
                className="obligation-card"
              >
                <div>
                  <span className={`status-pill ${obligation.status}`}>
                    {obligation.status.replace("_", " ")}
                  </span>
                  <h3>
                    {formatUsd(obligation.outstanding_amount.minor_units)}{" "}
                    outstanding
                  </h3>
                  <p>
                    {shortAddress(obligation.debtor_address)} owes{" "}
                    {shortAddress(obligation.creditor_address)} · original{" "}
                    {formatUsd(obligation.amount.minor_units)}
                  </p>
                </div>
                {isDebtor && obligation.status === "pending" && (
                  <div className="inline-actions">
                    {(["approve", "reject"] as const).map((decision) => (
                      <button
                        key={decision}
                        className={decision === "reject" ? "secondary" : ""}
                        disabled={isGroupWritePending(dashboard)}
                        onClick={() =>
                          void decideObligation(
                            dashboard,
                            group,
                            obligation.obligation_id,
                            decision,
                          )
                        }
                      >
                        {decision === "approve"
                          ? "Approve in ResVault"
                          : "Reject"}
                      </button>
                    ))}
                  </div>
                )}
                {maySettle && (
                  <form
                    className="inline-settlement"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const amount =
                        settlements[obligation.obligation_id] ?? "";
                      void settleObligation(
                        dashboard,
                        group,
                        obligation.obligation_id,
                        amount,
                      );
                    }}
                  >
                    <label>
                      Partial or full amount
                      <input
                        value={settlements[obligation.obligation_id] ?? ""}
                        onChange={(event) =>
                          setSettlements((current) => ({
                            ...current,
                            [obligation.obligation_id]: event.target.value,
                          }))
                        }
                        placeholder={(
                          obligation.outstanding_amount.minor_units / 100
                        ).toFixed(2)}
                        inputMode="decimal"
                        required
                      />
                    </label>
                    <button disabled={isGroupWritePending(dashboard)}>
                      Settle with credits
                    </button>
                  </form>
                )}
              </article>
            );
          })}
        </div>
      )}
      <MutationError
        error={dashboard.decision.error ?? dashboard.settlement.error}
      />
    </section>
  );
}

function NotificationsPanel({
  actorAddress,
  group,
}: {
  actorAddress: string;
  group: GroupOverview;
}) {
  return (
    <section className="panel notifications-panel">
      <h2>Notifications</h2>
      {group.notifications.length === 0 ? (
        <p className="empty-copy">
          No new group notifications for {shortAddress(actorAddress)}.
        </p>
      ) : (
        <ul>
          {group.notifications.map((notice) => (
            <li key={notice.notification_id}>
              <strong>{notice.kind.replaceAll("_", " ")}</strong>
              <span>{notice.message}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

async function decideObligation(
  dashboard: Dashboard,
  group: GroupOverview,
  obligationId: string,
  decision: "approve" | "reject",
) {
  const parameters = {
    group_id: group.group_id,
    obligation_id: obligationId,
    decision,
    expected_version: group.provenance.projection_version,
  };
  const intent = await requestSignature(
    "split.approve",
    obligationId,
    parameters,
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

async function settleObligation(
  dashboard: Dashboard,
  group: GroupOverview,
  obligationId: string,
  amount: string,
) {
  const amountMinorUnits = usdToMinorUnits(amount);
  const parameters = {
    group_id: group.group_id,
    obligation_id: obligationId,
    amount_minor_units: amountMinorUnits,
    expected_version: group.provenance.projection_version,
  };
  const intent = await requestSignature(
    "settlement.authorize",
    obligationId,
    parameters,
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

type ContractAction = "split.approve" | "credits.fund" | "settlement.authorize";

function isGroupWritePending(dashboard: Dashboard): boolean {
  return (
    dashboard.member.isPending ||
    dashboard.expense.isPending ||
    dashboard.decision.isPending ||
    dashboard.credits.isPending ||
    dashboard.settlement.isPending
  );
}

async function requestSignature(
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
    throw new Error("ResVault signed another action");
  return { ...signed, action };
}

function parseShares(value: string): Record<string, number> {
  const result: Record<string, number> = {};
  for (const line of value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)) {
    const separator = line.indexOf("=");
    if (separator < 0) throw new Error("Each share must use wallet=amount");
    const address = line.slice(0, separator).trim().toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(address))
      throw new Error("A share has an invalid wallet address");
    if (address in result) throw new Error("Each wallet may appear only once");
    result[address] = usdToMinorUnits(line.slice(separator + 1).trim());
  }
  if (Object.keys(result).length === 0)
    throw new Error("At least one share is required");
  return result;
}

function DashboardState({
  text,
  error = false,
}: {
  text: string;
  error?: boolean;
}) {
  return (
    <section
      className={`dashboard-state ${error ? "error" : ""}`}
      aria-live="polite"
    >
      <span className="loading-orb" aria-hidden="true" />
      <h2>{text}</h2>
    </section>
  );
}

function MutationError({ error }: { error: Error | null }) {
  return error === null ? null : (
    <p className="form-error" role="alert">
      {errorMessage(error)}
    </p>
  );
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The group request failed.";
}

function shortAddress(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function formatTimestamp(value: string | null): string {
  return value === null
    ? "No events yet"
    : `Updated ${new Date(value).toLocaleString()}`;
}
