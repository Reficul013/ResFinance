import { usdToMinorUnits } from "../finance/money";

export function parseShares(value: string): Record<string, number> {
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
