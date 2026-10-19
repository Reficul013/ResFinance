import {
  memberDisplayName,
  shortAddress,
  type GroupMemberLike,
} from "./members";

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
