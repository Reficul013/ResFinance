export const CRYPTO_ASSETS = ["BTC", "ETH", "SOL"] as const;

export type CryptoAsset = (typeof CRYPTO_ASSETS)[number];

export function isCryptoAsset(value: string): value is CryptoAsset {
  return CRYPTO_ASSETS.some((asset) => asset === value);
}
