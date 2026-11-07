// Spike: does an iMessage round trip work through Photon?
// PASS = you text the project's iMessage line and get "echo: <your text>" back.
// Run: just spike-photon
import { config } from "dotenv";
import { Spectrum } from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";

config({ path: new URL("../.env", import.meta.url).pathname });

if (!process.env.SPECTRUM_PROJECT_ID || !process.env.SPECTRUM_PROJECT_SECRET) {
  console.error("FAIL: set SPECTRUM_PROJECT_ID and SPECTRUM_PROJECT_SECRET in spikes/.env (app.photon.codes > project Settings)");
  process.exit(1);
}

const app = await Spectrum({
  projectId: process.env.SPECTRUM_PROJECT_ID,
  projectSecret: process.env.SPECTRUM_PROJECT_SECRET,
  providers: [imessage.config()],
});
console.log("Listening. Text the project's iMessage line from your phone...");

for await (const [space, message] of app.messages) {
  const t0 = Date.now();
  console.log(`[${new Date().toLocaleTimeString()}] in:`, JSON.stringify(message.content));
  if (message.content.type === "text") {
    await space.send(`echo: ${message.content.text}`);
    console.log(`  replied in ${Date.now() - t0}ms -> PASS if it arrived on your phone`);
  }
}
