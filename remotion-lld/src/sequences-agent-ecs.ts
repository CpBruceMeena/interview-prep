import { SequenceData } from "./SequenceDiagram";

export const ECS_AGENT_SEQUENCES: SequenceData[] = [
  // ═══════════════════════════════════════════════════════════
  // ECS AGENT DEPLOYMENT FLOW
  // ═══════════════════════════════════════════════════════════

  {
    id: "ecs-agent-deployment-flow",
    title: "ECS Agent Production Deployment",
    subtitle:
      "Code push → CI/CD → Docker build → ECR → ECS Blue/Green → Secrets → Health Check → Live",
    actors: [
      "Developer",
      "CI/CD (GitHub Actions)",
      "ECR",
      "ECS (Fargate)",
      "Secrets & DB",
    ],
    steps: [
      {
        from: 0,
        to: 1,
        label: "git push origin main",
        detail: "Agent code + task definition",
      },
      {
        from: 1,
        to: 1,
        label: "Run tests + lint + bandit",
        detail: "pytest, mypy, security scan",
      },
      {
        from: 1,
        to: 2,
        label: "docker build & push",
        detail: "agent-orchestrator:abc1234",
      },
      {
        from: 2,
        to: 1,
        label: "Image stored in ECR",
        detail: "Immutable artifact with SHA256",
      },
      {
        from: 1,
        to: 3,
        label: "Update ECS task definition",
        detail: "New image + env overrides",
      },
      {
        from: 3,
        to: 4,
        label: "Fetch secrets from Secrets Mgr",
        detail: "API keys, DB URL, Redis URL",
      },
      {
        from: 4,
        to: 3,
        label: "Credentials injected as env",
        detail: "Secrets never written to disk",
      },
      {
        from: 3,
        to: 2,
        label: "Pull new container image",
        detail: "ECR-backed with image tag",
      },
      {
        from: 3,
        to: 3,
        label: "Blue/Green: start new tasks",
        detail: "Desired count: 3 new tasks",
      },
      {
        from: 3,
        to: 3,
        label: "Health check: GET /health",
        detail: "curl -f http://localhost:8080/health",
      },
      {
        from: 3,
        to: 3,
        label: "200 OK — tasks healthy",
        detail: "ALB registers new target group",
      },
      {
        from: 3,
        to: 3,
        label: "Drain old tasks (connection drain)",
        detail: "90s timeout for in-flight requests",
      },
      {
        from: 3,
        to: 1,
        label: "✅ 3/3 tasks stable",
        detail: "Deployment circuit breaker: off",
      },
      {
        from: 1,
        to: 0,
        label: "✅ Production deployed!",
        detail: "Slack notification sent",
      },
    ],
    durationInFrames: 420,
  },

  // ═══════════════════════════════════════════════════════════
  // ECS AGENT REQUEST PROCESSING FLOW
  // ═══════════════════════════════════════════════════════════

  {
    id: "ecs-agent-request-flow",
    title: "Agent Request Processing — Production Runtime",
    subtitle:
      "Client → ALB → ECS Agent → RDS (History) → Redis (Session) → LLM API → Streaming Response",
    actors: ["Client", "ALB", "ECS Agent", "Redis Cache", "RDS Database", "LLM API"],
    steps: [
      {
        from: 0,
        to: 1,
        label: "POST /api/v1/chat",
        detail: "JWT auth + user query",
      },
      {
        from: 1,
        to: 2,
        label: "Route to healthy task",
        detail: "Least outstanding requests",
      },
      {
        from: 2,
        to: 3,
        label: "Rate limit check",
        detail: "Token bucket: 10 req/s per user",
      },
      {
        from: 3,
        to: 2,
        label: "Token consumed OK",
        detail: "Remaining: 7 tokens",
      },
      {
        from: 2,
        to: 4,
        label: "Load conversation history",
        detail: "SELECT * FROM sessions WHERE id = ?",
      },
      {
        from: 4,
        to: 2,
        label: "40 past messages loaded",
        detail: "System prompt + history window",
      },
      {
        from: 2,
        to: 3,
        label: "Cache active session state",
        detail: "Redis: TTL = 15 min session",
      },
      {
        from: 2,
        to: 5,
        label: "ReAct loop: call LLM",
        detail: "system + history + available tools",
      },
      {
        from: 5,
        to: 2,
        label: "LLM response (with tool call)",
        detail: "Model: claude-3.5-sonnet",
      },
      {
        from: 2,
        to: 4,
        label: "Store updated conversation",
        detail: "INSERT into llm_cost_log + sessions",
      },
      {
        from: 2,
        to: 3,
        label: "Update session step + cost",
        detail: "step_count: 3, total_cost: $0.002",
      },
      {
        from: 2,
        to: 2,
        label: "Emit metrics to CloudWatch",
        detail: "Latency: 1.2s, Tokens: 450, Cost: $0.002",
      },
      {
        from: 2,
        to: 1,
        label: "StreamingResponse (SSE)",
        detail: "Chunked transfer encoding",
      },
      {
        from: 1,
        to: 0,
        label: "✅ Real-time streaming output",
        detail: "Agent response delivered",
      },
    ],
    durationInFrames: 420,
  },
];
