import { useEffect, useId, useRef, useState } from "react";

import {
  memberCountLabel,
  shortAddress,
  type GroupMemberLike,
} from "./members";

type CopyStatus = { address: string; ok: boolean } | null;

export function MembersMenu({
  actorAddress,
  ownerAddress,
  members,
}: {
  actorAddress: string;
  ownerAddress: string;
  members: readonly GroupMemberLike[];
}) {
  const [open, setOpen] = useState(false);
  const [copyStatus, setCopyStatus] = useState<CopyStatus>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popoverId = useId();
  const active = members.filter((member) => member.active);

  useEffect(() => {
    if (!open) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (copyStatus === null) return;
    const timer = window.setTimeout(() => setCopyStatus(null), 2000);
    return () => window.clearTimeout(timer);
  }, [copyStatus]);

  async function copyAddress(address: string) {
    try {
      await navigator.clipboard.writeText(address);
      setCopyStatus({ address, ok: true });
    } catch {
      setCopyStatus({ address, ok: false });
    }
  }

  return (
    <div className="members-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="members-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((current) => !current)}
      >
        {memberCountLabel(active.length)}
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div
          id={popoverId}
          className="members-popover"
          role="dialog"
          aria-label="Group members"
        >
          <ul>
            {active.map((member) => {
              const status =
                copyStatus?.address === member.actor_address
                  ? copyStatus
                  : null;
              return (
                <li key={member.actor_address}>
                  <div className="member-row-name">
                    <span className="member-display-name">
                      {member.display_name}
                    </span>
                    {member.actor_address === ownerAddress && (
                      <span className="member-tag">Owner</span>
                    )}
                    {member.actor_address === actorAddress && (
                      <span className="member-tag">You</span>
                    )}
                  </div>
                  <div className="member-row-wallet">
                    <code title={member.actor_address}>
                      {shortAddress(member.actor_address)}
                    </code>
                    <button
                      type="button"
                      className="member-copy"
                      aria-label={`Copy ${member.display_name}'s wallet address`}
                      onClick={() => void copyAddress(member.actor_address)}
                    >
                      {status === null
                        ? "Copy"
                        : status.ok
                          ? "Copied"
                          : "Copy failed"}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
