export function unlockErrorMessage(error: unknown): string {
  const message =
    error instanceof Error ? error.message : "ResWallet request failed";
  if (
    message === "password or encrypted ResWallet seed is invalid" ||
    message === "ResWallet password must be at least 12 characters"
  ) {
    return "Incorrect Password";
  }
  return message;
}
