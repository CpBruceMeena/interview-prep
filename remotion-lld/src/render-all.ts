import path from "path";
import fs from "fs";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const OUTPUT_DIR = path.resolve(__dirname, "..", "..", "docs", "assets", "videos");

async function renderAll() {
  console.log("📦 Bundling Remotion project...");
  const bundleLocation = await bundle({
    entryPoint: path.resolve(__dirname, "index.ts"),
    webpackOverride: (config) => config,
  });

  // Ensure output directory exists
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  const compositionIds = [
    "parking-lot-sequence",
    "chess-game-sequence",
    "tic-tac-toe-sequence",
    "snakes-and-ladders-sequence",
    "vending-machine-sequence",
    "lru-cache-sequence",
    "rate-limiter-sequence",
    "pub-sub-sequence",
    "movie-ticket-sequence",
    "splitwise-sequence",
    "cab-booking-sequence",
    "library-management-sequence",
    "car-rental-sequence",
    "atm-banking-sequence",
    "inventory-management-sequence",
    "payment-processing-sequence",
    "job-scheduling-sequence",
    "notification-service-sequence",
    "search-platform-sequence",
  ];

  console.log(`🎬 Rendering ${compositionIds.length} videos...\n`);

  for (const id of compositionIds) {
    console.log(`  Rendering: ${id}...`);

    const composition = await selectComposition({
      serveUrl: bundleLocation,
      id,
      inputProps: {},
    });

    const outputLocation = path.join(OUTPUT_DIR, `${id}.mp4`);

    await renderMedia({
      composition,
      serveUrl: bundleLocation,
      codec: "h264",
      outputLocation,
      inputProps: {},
      chromiumOptions: {
        gl: "angle",
      },
    });

    const stats = fs.statSync(outputLocation);
    console.log(`  ✅ ${id}.mp4 (${(stats.size / 1024 / 1024).toFixed(1)} MB)\n`);
  }

  console.log("🎉 All videos rendered successfully!");
}

renderAll().catch((err) => {
  console.error("❌ Render failed:", err);
  process.exit(1);
});
