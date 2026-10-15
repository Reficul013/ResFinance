import { useCallback, useEffect, useState } from "react";

import {
  createChallenge,
  createSession,
  logoutSession,
  refreshSession,
} from "../../lib/api/client";
import {
  formatIntentTimestamp,
  getWalletIdentity,
  hashParameters,
  lockWallet,
  signIntent,
  type WalletIdentity,
} from "./resvault";

export type AuthenticationState =
  "checking" | "disconnected" | "ready" | "pending" | "authenticated" | "error";

interface Authentication {
  state: AuthenticationState;
  message: string;
  identity: WalletIdentity | null;
  actorAddress: string | null;
  accessToken: string | null;
  connect(): Promise<void>;
  logout(): Promise<void>;
}

let pendingInitialRefresh: ReturnType<typeof refreshSession> | null = null;

function refreshInitialSession(): ReturnType<typeof refreshSession> {
  pendingInitialRefresh ??= refreshSession().finally(() => {
    pendingInitialRefresh = null;
  });
  return pendingInitialRefresh;
}

export function useAuthentication(): Authentication {
  const [state, setState] = useState<AuthenticationState>("checking");
  const [message, setMessage] = useState("Checking wallet and session state…");
  const [identity, setIdentity] = useState<WalletIdentity | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [actorAddress, setActorAddress] = useState<string | null>(null);

  const inspectWallet = useCallback(async () => {
    try {
      const current = await getWalletIdentity();
      setIdentity(current);
      setState(current === null ? "disconnected" : "ready");
      setMessage(
        current === null
          ? "Initialize ResVault before connecting."
          : "ResVault is available. Continue to approve login.",
      );
    } catch {
      setState("disconnected");
      setMessage(
        "Install the ResVault extension to use wallet authentication.",
      );
    }
  }, []);

  useEffect(() => {
    let active = true;
    // React Strict Mode intentionally remounts effects in development. Share the
    // rotating refresh request so the remount cannot consume the same cookie
    // twice and let a racing 401 overwrite the valid refreshed session.
    refreshInitialSession()
      .then((session) => {
        if (!active) return;
        setAccessToken(session.access_token);
        setActorAddress(session.actor_address);
        setState("authenticated");
        setMessage("Authenticated with a rotated ResilientDB-backed session.");
      })
      .catch(() => {
        if (active) void inspectWallet();
      });
    return () => {
      active = false;
    };
  }, [inspectWallet]);

  const connect = useCallback(async () => {
    setState("pending");
    setMessage("Preparing a short-lived login challenge…");
    try {
      const current = identity ?? (await getWalletIdentity());
      if (current === null) throw new Error("ResVault is not initialized.");
      setIdentity(current);
      const challenge = await createChallenge(current);
      const origin = window.location.origin;
      const parameters = { challenge: challenge.challenge, origin };
      const issuedAt = new Date();
      const intent = await signIntent({
        version: 1,
        intent_id: crypto.randomUUID(),
        action: "auth.login",
        resource_id: challenge.challenge_id,
        parameters,
        parameters_hash: await hashParameters(parameters),
        nonce: crypto.randomUUID(),
        issued_at: formatIntentTimestamp(issuedAt),
        expires_at: formatIntentTimestamp(
          new Date(issuedAt.getTime() + 5 * 60 * 1000),
        ),
        origin,
        audience: "resfinance-api",
        network_id: "pinned-local-network",
      });
      const session = await createSession(challenge.challenge, intent);
      setAccessToken(session.access_token);
      setActorAddress(session.actor_address);
      setState("authenticated");
      setMessage(
        "Wallet challenge approved. Access token is held in memory only.",
      );
    } catch (error) {
      setState("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "Wallet authentication failed.",
      );
    }
  }, [identity]);

  const logout = useCallback(async () => {
    if (accessToken === null) return;
    try {
      await logoutSession(accessToken);
    } finally {
      try {
        await lockWallet();
      } catch {
        // The backend session is still revoked if the extension is unavailable.
      }
      setAccessToken(null);
      setActorAddress(null);
      await inspectWallet();
    }
  }, [accessToken, inspectWallet]);

  return {
    state,
    message,
    identity,
    actorAddress,
    accessToken,
    connect,
    logout,
  };
}
