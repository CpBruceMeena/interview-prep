# 🚀 Agent Deployment on AWS ECS — Production Infrastructure

> **Target:** Principal Engineer | **Focus:** Full production deployment architecture for AI agents on AWS ECS

---

## 1. ARCHITECTURE OVERVIEW

```
                      ┌──────────────────────┐
                      │   Route 53 / CloudFront│
                      └──────────┬───────────┘
                                 │
                      ┌──────────▼───────────┐
                      │   Application Load    │
                      │   Balancer (ALB)      │
                      └──────────┬───────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │ ECS Task │ │ ECS Task │ │ ECS Task │
             │ Agent #1 │ │ Agent #2 │ │ Agent #N │
             └────┬─────┘ └────┬─────┘ └────┬─────┘
                  │            │            │
     ┌────────────┼────────────┼────────────┼──────────┐
     │            ▼            ▼            ▼          │
     │      ┌─────────────────────────────────────┐    │
     │      │         AWS Services                │    │
     │      │                                     │    │
     │      │  ┌────────┐ ┌────────┐ ┌────────┐  │    │
     │      │  │ElastiCache│ │RDS    │ │ SQS   │  │    │
     │      │  │(Redis) │ │(PG)   │ │(Queue)│  │    │
     │      │  └────────┘ └────────┘ └────────┘  │    │
     │      │  ┌────────┐ ┌────────┐ ┌────────┐  │    │
     │      │  │S3 (Logs)│ │CW Logs│ │X-Ray  │  │    │
     │      │  └────────┘ └────────┘ └────────┘  │    │
     │      └─────────────────────────────────────┘    │
     └────────────────────────────────────────────────┘
```

---

## 2. ECS INFRASTRUCTURE (Terraform)

### 2.1 ECS Cluster & Service

```hcl
# terraform/ecs/main.tf

resource "aws_ecs_cluster" "agent_cluster" {
  name = "agent-production"
  
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  
  tags = {
    Name        = "agent-production"
    Environment = "production"
  }
}

resource "aws_ecs_task_definition" "agent" {
  family                   = "agent-orchestrator"
  requires_compatibilities = ["FARGATE"]
  network_mode            = "awsvpc"
  cpu                     = 2048   # 2 vCPU
  memory                  = 8192   # 8 GB RAM
  execution_role_arn      = aws_iam_role.ecs_execution.arn
  task_role_arn           = aws_iam_role.agent_task.arn
  
  container_definitions = jsonencode([
    {
      name  = "agent-orchestrator"
      image = "${aws_ecr_repository.agent.repository_url}:latest"
      
      portMappings = [{
        containerPort = 8080
        protocol      = "tcp"
      }]
      
      environment = [
        { name = "ENVIRONMENT",        value = "production" },
        { name = "LOG_LEVEL",          value = "INFO" },
        { name = "MAX_STEPS",          value = "25" },
        { name = "RATE_LIMIT_RPS",     value = "100" },
      ]
      
      secrets = [
        { name = "OPENAI_API_KEY",      valueFrom = "arn:aws:secretsmanager:us-east-1:xxxxx:secret:openai-api-key" },
        { name = "ANTHROPIC_API_KEY",   valueFrom = "arn:aws:secretsmanager:us-east-1:xxxxx:secret:anthropic-api-key" },
        { name = "DATABASE_URL",        valueFrom = "arn:aws:secretsmanager:us-east-1:xxxxx:secret:database-url" },
        { name = "REDIS_URL",           valueFrom = "arn:aws:secretsmanager:us-east-1:xxxxx:secret:redis-url" },
      ]
      
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/agent-orchestrator"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }
      
      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
      
      ulimits = [{
        name        = "nofile"
        softLimit   = 65536
        hardLimit   = 65536
      }]
      
      resourceRequirements = [
        { type = "GPU", value = "1" }  # If using GPU inference
      ]
    }
  ])
  
  tags = {
    Environment = "production"
  }
}

resource "aws_ecs_service" "agent" {
  name            = "agent-orchestrator-service"
  cluster         = aws_ecs_cluster.agent_cluster.id
  task_definition = aws_ecs_task_definition.agent.arn
  desired_count   = 5
  launch_type     = "FARGATE"
  
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.agent_sg.id]
  }
  
  load_balancer {
    target_group_arn = aws_lb_target_group.agent.arn
    container_name   = "agent-orchestrator"
    container_port   = 8080
  }
  
  deployment_controller {
    type = "CODE_DEPLOY"  # Blue/Green deployments
  }
  
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  
  auto_scaling_policy = {
    target_tracking_scaling_policy_configuration {
      target_value = 70.0
      predefined_metric_specification {
        predefined_metric_type = "ECSServiceAverageCPUUtilization"
      }
      scale_in_cooldown  = 300
      scale_out_cooldown = 60
    }
  }
}

# Auto-scaling
resource "aws_appautoscaling_target" "agent" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.agent_cluster.name}/${aws_ecs_service.agent.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 3
  max_capacity       = 20
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "cpu-scaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.agent.resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  
  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "memory" {
  name               = "memory-scaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.agent.resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  
  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
  }
}

# Custom metric scaling (agent session count)
resource "aws_appautoscaling_policy" "sessions" {
  name               = "active-sessions-scaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.agent.resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  
  target_tracking_scaling_policy_configuration {
    target_value       = 100.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
    
    customized_metric_specification {
      metrics = [{
        id        = "m1"
        return_data = true
        metric_stat {
          metric {
            namespace   = "Agent"
            metric_name = "ActiveSessions"
            dimensions  = [{
              name  = "Service"
              value = "agent-orchestrator"
            }]
          }
          stat = "Sum"
          unit  = "Count"
        }
      }]
    }
  }
}
```

### 2.2 Networking & Security

```hcl
# terraform/network/main.tf

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  
  tags = { Name = "agent-production" }
}

resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
  
  tags = { Name = "agent-private-${count.index}" }
}

resource "aws_subnet" "public" {
  count             = 3
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 3}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
  
  map_public_ip_on_launch = true
  tags = { Name = "agent-public-${count.index}" }
}

# Security group for agent tasks
resource "aws_security_group" "agent_sg" {
  name        = "agent-orchestrator-sg"
  description = "Security group for agent orchestrator tasks"
  vpc_id      = aws_vpc.main.id
  
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }
  
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# VPC Endpoints for private subnet access
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.us-east-1.secretsmanager"
  vpc_endpoint_type = "Interface"
  subnet_ids        = aws_subnet.private[*].id
}
```

### 2.3 IAM Roles & Policies

```hcl
# terraform/iam/main.tf

resource "aws_iam_role" "ecs_execution" {
  name = "ecs-execution-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "agent_task" {
  name = "agent-task-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
}

# Task role permissions
resource "aws_iam_policy" "agent_task" {
  name = "agent-task-policy"
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "kms:Decrypt"
        ]
        Resource = [
          "arn:aws:secretsmanager:us-east-1:xxxxx:secret:*",
          "arn:aws:kms:us-east-1:xxxxx:key/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject"
        ]
        Resource = ["arn:aws:s3:::agent-logs/*"]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage"
        ]
        Resource = ["arn:aws:sqs:us-east-1:xxxxx:agent-queue"]
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords"
        ]
        Resource = ["*"]
      }
    ]
  })
}
```

---

## 3. API & DATA FLOW

### 3.1 API Design

```python
# app/main.py — FastAPI application
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional

app = FastAPI(
    title="Agent Orchestrator API",
    version="1.0.0",
    docs_url="/api/docs"
)

# ─── Request/Response Models ──────────────────────

class AgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    user_id: str = Field(..., min_length=1)
    session_config: Optional[dict] = {
        "max_steps": 25,
        "temperature": 0.3,
        "model_preference": "auto"
    }

class AgentResponse(BaseModel):
    response: str
    conversation_id: str
    model_used: str
    tokens_used: int
    cost: float
    latency_ms: int
    tool_calls: list

class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    active_sessions: int
    uptime_seconds: float

# ─── API Endpoints ────────────────────────────────

@app.post("/api/v1/chat", response_model=AgentResponse)
async def chat(request: AgentRequest):
    """
    Main agent endpoint.
    Handles user queries and returns agent responses.
    """
    try:
        result = await agent_orchestrator.process(
            query=request.query,
            conversation_id=request.conversation_id,
            user_id=request.user_id,
            config=request.session_config
        )
        return AgentResponse(**result)
    except BudgetExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

@app.post("/api/v1/chat/stream")
async def chat_stream(request: AgentRequest):
    """
    Streaming endpoint for real-time agent responses.
    Uses Server-Sent Events (SSE).
    """
    return StreamingResponse(
        agent_orchestrator.process_stream(
            query=request.query,
            conversation_id=request.conversation_id,
            user_id=request.user_id
        ),
        media_type="text/event-stream"
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for ECS load balancer."""
    return HealthResponse(
        status="healthy",
        active_sessions=session_manager.active_count(),
        uptime_seconds=time.time() - startup_time
    )

@app.post("/api/v1/conversations/{conv_id}/feedback")
async def submit_feedback(conv_id: str, rating: int, comment: str = None):
    """Submit user feedback for a conversation."""
    await feedback_service.store(conv_id, rating, comment)
    return {"status": "ok"}
```

### 3.2 Database Flow

```
User Request
    │
    ▼
┌──────────────────────────────┐
│  API Gateway / ALB            │
│  - Auth (JWT validation)      │
│  - Rate limiting              │
│  - Request logging            │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  Agent Orchestrator (ECS)     │
│                               │
│  1. Validate input            │
│  2. Load conversation history │ ← RDS (PostgreSQL)
│  3. Route to LLM model       │
│  4. Execute ReAct loop       │
│  5. Store conversation state │ → RDS (PostgreSQL)
│  6. Store session state     │ → ElastiCache (Redis)
│  7. Log traces               │ → CloudWatch Logs
└──────────────────────────────┘
```

### 3.3 Database Schema

```sql
-- Sessions table (for active agent sessions)
CREATE TABLE agent_sessions (
    session_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  VARCHAR(64) UNIQUE NOT NULL,
    user_id          VARCHAR(128) NOT NULL,
    state            JSONB NOT NULL,          -- Full agent state
    step_count       INTEGER DEFAULT 0,
    max_steps        INTEGER DEFAULT 25,
    total_cost       DECIMAL(10,6) DEFAULT 0.0,
    status           VARCHAR(16) DEFAULT 'active',
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    expires_at       TIMESTAMPTZ DEFAULT NOW() + INTERVAL '24 hours',
    
    INDEX idx_sessions_user (user_id, created_at DESC),
    INDEX idx_sessions_status (status) WHERE status = 'active'
);

-- Cost tracking table
CREATE TABLE llm_cost_log (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  VARCHAR(64) NOT NULL,
    model            VARCHAR(64) NOT NULL,
    input_tokens     INTEGER NOT NULL,
    output_tokens    INTEGER NOT NULL,
    cost             DECIMAL(10,6) NOT NULL,
    latency_ms       INTEGER,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    
    INDEX idx_cost_conv (conversation_id),
    INDEX idx_cost_time (created_at)
) PARTITION BY RANGE (created_at);

-- Monthly cost partitions
CREATE TABLE llm_cost_2026_07 PARTITION OF llm_cost_log
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

---

## 4. MONITORING & ALERTING

### 4.1 CloudWatch Dashboard

```hcl
# terraform/monitoring/dashboard.tf

resource "aws_cloudwatch_dashboard" "agent" {
  dashboard_name = "agent-production"
  
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          metrics = [
            ["ECS/ContainerInsights", "CpuUtilized", { "stat": "Average" }],
            [".", "MemoryUtilized", { "stat": "Average" }]
          ]
          period = 300
          stat   = "Average"
          region = "us-east-1"
          title  = "ECS Resource Utilization"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["Agent", "RequestCount", { "stat": "Sum" }],
            [".", "SuccessCount", { "stat": "Sum" }],
            [".", "ErrorCount", { "stat": "Sum" }]
          ]
          period = 60
          stat   = "Sum"
          region = "us-east-1"
          title  = "API Request Metrics"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["Agent", "P95Latency", { "stat": "p95" }],
            [".", "P99Latency", { "stat": "p99" }]
          ]
          period = 60
          stat   = "p95"
          region = "us-east-1"
          title  = "Latency Percentiles"
        }
      },
      {
        type = "metric"
        properties = {
          metrics = [
            ["Agent", "LLMCost", { "stat": "Sum", "period": 3600 }]
          ]
          period = 3600
          stat   = "Sum"
          region = "us-east-1"
          title  = "LLM Cost ($/hour)"
        }
      },
      {
        type = "log"
        properties = {
          query   = "fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20"
          logGroupNames = ["/ecs/agent-orchestrator"]
          title   = "Recent Errors"
          region  = "us-east-1"
        }
      }
    ]
  })
}
```

### 4.2 Alert Rules

```hcl
# terraform/monitoring/alarms.tf

# High error rate alarm
resource "aws_cloudwatch_metric_alarm" "high_error_rate" {
  alarm_name          = "agent-high-error-rate"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "ErrorCount"
  namespace           = "Agent"
  period              = "300"
  statistic           = "Sum"
  threshold           = "50"
  alarm_description   = "Agent error rate > 50 in 5 minutes"
  alarm_actions       = [aws_sns_topic.agent_alerts.arn]
  
  dimensions = {
    Service = "agent-orchestrator"
  }
}

# High latency alarm
resource "aws_cloudwatch_metric_alarm" "high_latency" {
  alarm_name          = "agent-high-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "3"
  metric_name         = "P95Latency"
  namespace           = "Agent"
  period              = "300"
  statistic           = "p95"
  threshold           = "30000"  # 30 seconds
  alarm_description   = "P95 latency > 30 seconds"
  alarm_actions       = [aws_sns_topic.agent_alerts.arn]
}

# Cost anomaly alarm
resource "aws_cloudwatch_metric_alarm" "cost_anomaly" {
  alarm_name          = "agent-cost-anomaly"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "LLMCost"
  namespace           = "Agent"
  period              = "3600"
  statistic           = "Sum"
  threshold           = "50"  # $50/hour
  alarm_description   = "LLM cost exceeded $50/hour"
  alarm_actions       = [aws_sns_topic.agent_alerts.arn]
}

# SNS topic for alerts
resource "aws_sns_topic" "agent_alerts" {
  name = "agent-production-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.agent_alerts.arn
  protocol  = "email"
  endpoint  = "team@example.com"  # Configure with actual email
}

resource "aws_sns_topic_subscription" "slack" {
  topic_arn = aws_sns_topic.agent_alerts.arn
  protocol  = "https"
  endpoint  = "https://hooks.slack.com/services/xxxxx/xxxxx"  # Slack webhook
}
```

### 4.3 Custom Metrics (Embedded Metric Format)

```python
# app/monitoring/metrics.py
from aws_embedded_metrics import metric_scope
from prometheus_client import Counter, Histogram, Gauge
import boto3

# Prometheus metrics (for local/self-hosted)
agent_requests = Counter('agent_requests_total', 'Total requests', ['status'])
agent_latency = Histogram('agent_latency_seconds', 'Request latency', 
                          buckets=[0.1, 0.5, 1, 2, 5, 10, 30])
agent_cost = Counter('agent_cost_total', 'Total cost in USD', ['model'])

# CloudWatch EMF metrics
@metric_scope
async def emit_agent_metrics(metrics):
    """Emit custom metrics to CloudWatch via Embedded Metric Format."""
    metrics.set_namespace("Agent")
    metrics.set_dimensions({"Service": "agent-orchestrator"})
    
    # Rate this request
    metrics.put_metric("RequestCount", 1, "Count")
    
    # Track latency
    metrics.put_metric("P95Latency", latency_ms, "Milliseconds")
    
    # Track cost
    metrics.put_metric("LLMCost", cost, "None")
    
    # Track active sessions
    metrics.put_metric("ActiveSessions", active_count, "Count")
```

---

## 5. CI/CD PIPELINE

```yaml
# .github/workflows/deploy-agent.yml
name: Deploy Agent to ECS

on:
  push:
    branches: [main]
    paths:
      - 'agent/**'
      - 'Dockerfile'
      - 'docker-compose.yml'

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: agent-orchestrator
  ECS_SERVICE: agent-orchestrator-service
  ECS_CLUSTER: agent-production

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-asyncio
      
      - name: Run tests
        run: pytest tests/ -v --cov=app --cov-report=xml
      
      - name: Run type checking
        run: mypy app/
      
      - name: Run security scan
        run: bandit -r app/ -f json -o security-report.json
  
  build-and-deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      
      - name: Build, tag, and push image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
      
      - name: Deploy to ECS (Blue/Green)
        run: |
          aws ecs update-service \
            --cluster $ECS_CLUSTER \
            --service $ECS_SERVICE \
            --task-definition agent-orchestrator \
            --force-new-deployment
      
      - name: Wait for stable deployment
        run: |
          aws ecs wait services-stable \
            --cluster $ECS_CLUSTER \
            --services $ECS_SERVICE
      
      - name: Run smoke tests
        run: |
          curl -f http://$ALB_DNS/health
          curl -f -X POST http://$ALB_DNS/api/v1/chat \
            -H "Content-Type: application/json" \
            -d '{"query":"Hello","user_id":"test"}'
```

---

## 6. COST MONITORING

```python
# app/monitoring/cost_monitor.py

class ECSCostMonitor:
    """Monitor and optimize ECS + LLM costs."""
    
    def __init__(self):
        self.ce_client = boto3.client('ce')  # Cost Explorer
        self.ecs_client = boto3.client('ecs')
    
    def get_daily_cost(self) -> dict:
        """Get daily cost breakdown."""
        end = datetime.utcnow()
        start = end - timedelta(days=1)
        
        response = self.ce_client.get_cost_and_usage(
            TimePeriod={
                'Start': start.strftime('%Y-%m-%d'),
                'End': end.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost', 'UsageQuantity'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
            ]
        )
        
        return {
            'total': sum(
                float(g['Metrics']['BlendedCost']['Amount'])
                for g in response['ResultsByTime'][0]['Groups']
            ),
            'by_service': {
                g['Keys'][0]: float(g['Metrics']['BlendedCost']['Amount'])
                for g in response['ResultsByTime'][0]['Groups']
            }
        }
    
    def get_optimization_recommendations(self) -> list:
        """Get cost optimization recommendations."""
        recommendations = []
        
        # Check ECS Fargate right-sizing
        for task in self._get_task_metrics():
            cpu_utilization = task['cpu_utilization']
            memory_utilization = task['memory_utilization']
            
            if cpu_utilization < 20 and memory_utilization < 30:
                recommendations.append({
                    'type': 'ecs_rightsizing',
                    'current': f"{task['cpu']}vCPU, {task['memory']}GB",
                    'suggested': 'Downsize to next tier',
                    'annual_savings': self._estimate_savings(task)
                })
        
        # Check idle resources
        if self._has_idle_tasks():
            recommendations.append({
                'type': 'idle_resources',
                'detail': 'Scheduling-based auto-scaling could reduce costs',
                'annual_savings': '$2,400'
            })
        
        # Check LLM model usage
        llm_report = self._get_llm_usage_report()
        if llm_report['cheaper_model_opportunity']:
            recommendations.append({
                'type': 'model_optimization',
                'detail': f"${llm_report['potential_savings']}/month could be saved "
                         f"by routing simple queries to cheaper models",
                'annual_savings': f"${llm_report['potential_savings'] * 12}"
            })
        
        return recommendations
```

---

## 7. INTERVIEW QUESTIONS & ANSWERS

### Q1: How do you deploy an AI agent system to production on AWS ECS?

**Answer:** 

1. **Containerize**: Build a Docker image with the agent code, dependencies, and health checks
2. **Push to ECR**: Store images in Amazon Elastic Container Registry with version tags
3. **Define task**: Create ECS task definition with Fargate (serverless) or EC2 launch type
4. **Configure service**: Set up ECS service behind ALB with auto-scaling (CPU/memory/custom metrics)
5. **Set up networking**: VPC, subnets, security groups, VPC endpoints for Secrets Manager
6. **Configure secrets**: Store API keys in Secrets Manager, reference via task definition
7. **CI/CD**: GitHub Actions pipeline for testing, building, and blue/green deployment
8. **Monitor**: CloudWatch dashboards, custom metrics, alerting via SNS → Slack/Email
9. **Scale**: Auto-scaling based on CPU/memory utilization and active session count

### Q2: How do you handle rate limiting for LLM APIs in production?

**Answer:**

```python
class LLMRateLimiter:
    """Multi-layer rate limiting for LLM APIs."""
    
    def __init__(self):
        self.per_user = TokenBucket(rate=10, burst=20)   # 10 req/s per user
        self.per_model = TokenBucket(rate=100, burst=200) # 100 req/s per model
        self.global_limit = TokenBucket(rate=1000, burst=2000)  # Global limit
    
    async def check_limits(self, user_id: str, model: str) -> bool:
        """Check all rate limits before making an API call."""
        return all([
            await self.per_user.consume(user_id),
            await self.per_model.consume(model),
            await self.global_limit.consume("global")
        ])
```

### Q3: How do you ensure zero-downtime deployments?

**Answer:**
- Use **Blue/Green deployment** via CodeDeploy
- Configure **deployment circuit breaker** for automatic rollback
- Set **health check grace period** to avoid premature task termination
- Implement **connection draining** to allow in-flight requests to complete
- Use **rolling update** with `maxSurge=2, maxUnavailable=0`

### Q4: How do you monitor LLM costs at scale?

**Answer:**
- Track every LLM call with model, input/output tokens, and cost
- Set per-user, per-session, and per-month budgets
- Alert on cost anomalies (>$50/hour spike)
- Use budget-aware routing (downgrade model when budget is tight)
- Regular cost optimization reports with action recommendations

---

> **Next:** [System/User/Assistant Roles](10_SYSTEM_USER_ASSISTANT_ROLES.md) → Understanding message roles in LLM interactions
