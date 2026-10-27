import {
  memberDisplayName,
  shortAddress,
  type GroupMemberLike,
} from "./members";

export function PersonName({
  address,
  members,
  actorAddress,
  capitalized = true,
}: {
  address: string;
  members: readonly GroupMemberLike[];
  actorAddress: string;
  capitalized?: boolean;
}) {
  if (address.toLowerCase() === actorAddress.toLowerCase())
    return <strong>{capitalized ? "You" : "you"}</strong>;
  return <MemberName address={address} members={members} />;
}

export function MemberName({
  address,
  members,
}: {
  address: string;
  members: readonly GroupMemberLike[];
}) {
  const name = memberDisplayName(members, address) ?? shortAddress(address);
  return (
    <span className="member-name" tabIndex={0}>
      {name}
      <span className="member-address" role="tooltip">
        {address}
      </span>
    </span>
  );
}
