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
    // LLD sequences
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

    // CI/CD sequences
    "cicd-end-to-end-pipeline",
    "cicd-blue-green-deployment",
    "cicd-canary-release",
    "cicd-artifact-promotion",
    "cicd-frontend-pipeline",
    "cicd-backend-pipeline",

    // Kubernetes sequences
    "k8s-pod-lifecycle",
    "k8s-container-states",
    "k8s-monitoring-stack",

    // Networks sequences
    "net-tls-handshake",
    "net-dns-resolution",
    "net-http2-vs-quic",

    // Distributed Systems sequences
    "ds-raft-leader-election",
    "ds-twopc-vs-saga",
    "ds-consistent-hashing",
    "ds-swim-gossip",

    // Architecture sequences
    "arch-cqrs-event-sourcing",
    "arch-circuit-breaker",
    "arch-microservices-decomposition",

    // AWS sequences
    "aws-vpc-peering-vs-tgw",
    "aws-route53-dns-routing",
    "aws-s3-consistency",
    "aws-lambda-lifecycle",
    "aws-sqs-long-polling",
    "aws-sns-fanout",
    "aws-kinesis-shard-scaling",
    "aws-eventbridge-routing",
    "aws-iam-permission-boundary",
    "aws-kms-envelope-encryption",
    "aws-guardduty-multi-account",
    "aws-cognito-auth-flow",

    // ECS Agent sequences
    "ecs-agent-deployment-flow",
    "ecs-agent-request-flow",
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
