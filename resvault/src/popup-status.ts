export function unlockErrorMessage(error: unknown): string {
  const message =
    error instanceof Error ? error.message : "ResVault request failed";
  if (
    message === "password or encrypted ResVault seed is invalid" ||
    message === "ResVault password must be at least 12 characters"
  ) {
    return "Incorrect Password";
  }
  return message;
}
