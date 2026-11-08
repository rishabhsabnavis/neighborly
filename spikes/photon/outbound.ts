// Spike: can the agent START a conversation (no inbound message first)?
// Neighborly flow depends on this: we text policyholders in a disaster zone.
// PASS = each number in OUTBOUND_TO gets the check-in text, and a reply
// ("1", "2", anything) is printed here within the listen window.
// Run: just spike-photon-out
import { config } from "dotenv";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

config({ path: new URL("../.env", import.meta.url).pathname });

const to = (process.env.OUTBOUND_TO ?? "").split(",").map((s) => s.trim()).filter(Boolean);
if (!process.env.SPECTRUM_PROJECT_ID || !process.env.SPECTRUM_PROJECT_SECRET || to.length === 0) {
  console.error("FAIL: set SPECTRUM_PROJECT_ID, SPECTRUM_PROJECT_SECRET and OUTBOUND_TO (comma-separated +1 numbers) in spikes/.env");
  process.exit(1);
}

const app = await Spectrum({
  projectId: process.env.SPECTRUM_PROJECT_ID,
  projectSecret: process.env.SPECTRUM_PROJECT_SECRET,
  providers: [imessage.config()],
});
const im = imessage(app);

for (const phone of to) {
  const t0 = Date.now();
  const space = await im.space.create(phone);
  await space.send("Spike test: are you safe? Reply 1 = safe, 2 = need help now.");
  console.log(`sent to ${phone} in ${Date.now() - t0}ms (space ${space.id})`);
}

const LISTEN_MS = 120_000;
console.log(`Listening ${LISTEN_MS / 1000}s for replies...`);
setTimeout(() => { console.log("listen window over"); process.exit(0); }, LISTEN_MS);
for await (const [space, message] of app.messages) {
  console.log(`[${new Date().toLocaleTimeString()}] reply in ${space.id}:`, JSON.stringify(message.content), "-> PASS");
}
