import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const OUTPUT_DIR = path.resolve(__dirname, "..", "..", "docs", "assets", "videos");

const COMPOSITION_IDS = [
  // ── LLD Sequences ──
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

  // ── CI/CD Deployment ──
  "cicd-end-to-end-pipeline",
  "cicd-blue-green-deployment",
  "cicd-canary-release",
  "cicd-artifact-promotion",
  "cicd-frontend-pipeline",
  "cicd-backend-pipeline",

  // ── Kubernetes ──
  "k8s-pod-lifecycle",
  "k8s-container-states",
  "k8s-monitoring-stack",

  // ── Computer Networks ──
  "net-tls-handshake",
  "net-dns-resolution",
  "net-http2-vs-quic",

  // ── Distributed Systems ──
  "ds-raft-leader-election",
  "ds-twopc-vs-saga",
  "ds-consistent-hashing",
  "ds-swim-gossip",

  // ── Software Architecture ──
  "arch-cqrs-event-sourcing",
  "arch-circuit-breaker",
  "arch-microservices-decomposition",

  // ── AWS — VPC & Networking ──
  "aws-vpc-peering-vs-tgw",
  "aws-route53-dns-routing",

  // ── AWS — Storage & Database ──
  "aws-s3-consistency",

  // ── AWS — Compute / Lambda ──
  "aws-lambda-lifecycle",

  // ── AWS — Messaging ──
  "aws-sqs-long-polling",
  "aws-sns-fanout",
  "aws-kinesis-shard-scaling",
  "aws-eventbridge-routing",

  // ── AWS — Security ──
  "aws-iam-permission-boundary",
  "aws-kms-envelope-encryption",
  "aws-guardduty-multi-account",
  "aws-cognito-auth-flow",
];

async function renderAll() {
  console.log("Bundling Remotion project...");
  const bundleLocation = await bundle({
    entryPoint: path.resolve(__dirname, "index.ts"),
    webpackOverride: (config) => config,
  });

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  console.log(`Rendering ${COMPOSITION_IDS.length} videos...\n`);

  for (const id of COMPOSITION_IDS) {
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
    console.log(`  OK ${id}.mp4 (${(stats.size / 1024 / 1024).toFixed(1)} MB)\n`);
  }

  console.log("All videos rendered successfully!");
}

renderAll().catch((err) => {
  console.error("Render failed:", err);
  process.exit(1);
});
