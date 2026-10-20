export interface GroupMemberLike {
  actor_address: string;
  display_name: string;
  active: boolean;
}

export function memberDisplayName(
  members: readonly GroupMemberLike[],
  address: string,
): string | null {
  const normalized = address.toLowerCase();
  const member = members.find(
    (item) => item.actor_address.toLowerCase() === normalized,
  );
  return member === undefined ? null : member.display_name;
}

export function memberCountLabel(count: number): string {
  return `${count} ${count === 1 ? "member" : "members"}`;
}

export function shortAddress(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-6)}`;
}
