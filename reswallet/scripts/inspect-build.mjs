import { readFile } from "node:fs/promises";

const manifest = JSON.parse(
  await readFile(new URL("../dist/manifest.json", import.meta.url)),
);
const content = await readFile(
  new URL("../dist/content.js", import.meta.url),
  "utf8",
);
const background = await readFile(
  new URL("../dist/background.js", import.meta.url),
  "utf8",
);
const popup = await readFile(
  new URL("../dist/popup.html", import.meta.url),
  "utf8",
);

const expectedOrigins = [
  "https://app.resfinance.local/*",
  "http://127.0.0.1:5173/*",
];
const expectedIcons = {
  16: "icons/reswallet-16.png",
  32: "icons/reswallet-32.png",
  48: "icons/reswallet-48.png",
  128: "icons/reswallet-128.png",
};

assert(
  JSON.stringify(manifest.host_permissions) === JSON.stringify(expectedOrigins),
  "host permissions are not exact",
);
assert(
  JSON.stringify(manifest.content_scripts?.[0]?.matches) ===
    JSON.stringify(expectedOrigins),
  "content-script origins are not exact",
);
assert(
  !JSON.stringify(manifest).includes("<all_urls>"),
  "manifest contains <all_urls>",
);
assert(
  JSON.stringify(manifest.icons) === JSON.stringify(expectedIcons),
  "extension icons are not exact",
);
assert(
  JSON.stringify(manifest.action?.default_icon) ===
    JSON.stringify(expectedIcons),
  "toolbar icons are not exact",
);
await Promise.all(
  Object.values(expectedIcons).map((icon) =>
    readFile(new URL(`../dist/${icon}`, import.meta.url)),
  ),
);
assert(
  content.includes("window.location.origin"),
  "content bridge does not bind exact origin",
);
assert(
  !content.includes("postMessage(e,`*`)"),
  "content bridge posts to wildcard origin",
);

for (const prohibited of [
  "privateKey",
  "getSigningKeys",
  "mnemonic",
  "password",
  "ciphertext",
  "derived_key",
]) {
  assert(
    !content.includes(prohibited),
    `content bridge exposes prohibited term: ${prohibited}`,
  );
}

assert(
  background.includes("Argon2id"),
  "background bundle has no Argon2id implementation",
);
assert(
  background.includes("AES-256-GCM"),
  "background bundle has no AES-256-GCM record",
);
assert(
  background.includes("explicit wallet approval"),
  "background bundle has no approval guard",
);
assert(
  popup.includes('<form id="setup"'),
  "wallet setup controls are not a form",
);
assert(
  popup.includes('<button id="create" type="submit"'),
  "wallet creation is not the setup form submit action",
);

console.log("ResWallet build inspection passed");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}
