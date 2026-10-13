import type { paths } from "./generated/schema";

type HealthResponse =
  paths["/api/v1/health"]["get"]["responses"][200]["content"]["application/json"];

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const request: RequestInit = { headers: { Accept: "application/json" } };
  if (signal !== undefined) {
    request.signal = signal;
  }
  const response = await fetch("/api/v1/health", request);
  if (!response.ok) {
    throw new Error(`Health request failed with ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
