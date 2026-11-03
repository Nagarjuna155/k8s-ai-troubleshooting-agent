# k8s-ai-troubleshooting-agent
An MCP-powered AI agent that troubleshoots Kubernetes clusters through natural-language conversation


# Kubernetes AI Troubleshooting Agent

An MCP-powered AI agent that troubleshoots Kubernetes clusters through
natural-language conversation. Ask about pods, deployments, logs, or
events in plain English, and get answers backed by real `kubectl` command
output — not hallucinated guesses.

## How it works

```
You (terminal)
     │
     ▼
LangChain agent (Ollama LLM + tool-calling loop)
     │
     ▼
MCP client  ──stdio──▶  k8s_mcp_server.py (FastMCP)
                             │
                             ▼
                     subprocess → kubectl CLI
                             │
                             ▼
                  Kubernetes cluster (API server)
```

The agent doesn't call `kubectl` directly. Instead, `k8s_mcp_server.py`
exposes a set of narrow, well-documented tools over MCP (Model Context
Protocol). The LLM reads each tool's docstring, decides which tool fits
the user's question, calls it, and turns the raw `kubectl` output into a
plain-English answer — including root-cause reasoning (e.g. spotting an
OOMKill in `describe pod` events, or a connection error in the logs of a
crashed container).

At startup, the agent asks you to pick a **cluster context** and a
**default namespace** from your kubeconfig. Those choices are passed to
the MCP server as environment variables (`K8S_CONTEXT`, `K8S_NAMESPACE`),
so every tool call is scoped to the cluster you chose and the LLM never
has to ask "which cluster?".

## Tools exposed

| Tool | What it does |
|---|---|
| `get_current_context` | Shows which cluster context and namespace this session is targeting |
| `list_available_contexts` | Runs `kubectl config get-contexts` — lists clusters in your kubeconfig |
| `list_available_namespaces` | Runs `kubectl get namespaces` — lists namespaces in a cluster |
| `list_pods` | Runs `kubectl get pods -o wide` — pod status (Running, CrashLoopBackOff, Pending, ...), for one namespace or all |
| `describe_pod` | Runs `kubectl describe pod` — containers, resource limits, node, and the Events section for root cause analysis |
| `get_pod_logs` | Runs `kubectl logs --tail 200` — recent logs, with optional container name and `previous=True` for crashed containers |
| `get_events` | Runs `kubectl get events --sort-by=.lastTimestamp` — scheduling failures, image pulls, OOM kills, volume errors |
| `list_deployments` | Runs `kubectl get deployments -o wide` — ready/available replica counts |
| `describe_deployment` | Runs `kubectl describe deployment` — details and rollout status |
| `get_rollout_history` | Runs `kubectl rollout history` — revision history of a deployment |
| `get_resource_usage` | Runs `kubectl top pods` — live CPU/memory usage (requires metrics-server) |
| `get_services` | Runs `kubectl get svc -o wide` — service type, cluster IP, and ports |

All tools are **read-only**. The agent can diagnose, but it can't change
anything in your cluster.

## Prerequisites

- Python 3.10+
- `kubectl` installed and on your `PATH`, with a kubeconfig that has at
  least one working cluster context
- [Ollama](https://ollama.com) installed, with a model pulled:
  ```bash
  ollama pull gemma4:26b
  ```
  (or any other local model you have — update the `model=` value in
  `k8s_agent_mcp.py` to match whatever `ollama list` shows you)
- Optional: [metrics-server](https://github.com/kubernetes-sigs/metrics-server)
  installed in the cluster, if you want `get_resource_usage` to work

## Setup

```bash
git clone https://github.com/Nagarjuna155/k8s-ai-troubleshooting-agent.git
cd k8s-ai-troubleshooting-agent
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python k8s_agent_mcp.py
```

On startup you'll be asked to choose a cluster context and namespace,
then you can start chatting.

Example session:
```
Kubernetes Troubleshooting Assistant — session setup

Select a cluster [1-2] (Enter for current: minikube): 

Available namespaces:
  1. default  (default)
  2. kube-system

Select a namespace [1-3] (Enter for 'default'): 3

Using cluster: minikube
Using default namespace: default

Ask about pods, deployments, logs, events, or RCA.
Type 'exit' or 'quit' to stop.

You: what's wrong in my namespace?
Assistant: payment-api-7d9f8b-xk2lp is in CrashLoopBackOff. The logs from
the previous container instance show a "connection refused" error to
postgres:5432, and the container exited with code 1.
Suggested next action: check that the postgres service has endpoints and
that the database pod is Running.

You: show me the postgres pods
Assistant: There is one postgres pod, postgres-0, and it is Running
with 0 restarts.

You: exit
Goodbye.
```

## Files

| File | Purpose |
|---|---|
| `k8s_mcp_server.py` | MCP server exposing kubectl-backed tools, scoped to the chosen cluster context and namespace |
| `k8s_agent_mcp.py` | Interactive agent runner (LangChain + Ollama + MCP client): session setup, system prompt, and a chat loop that keeps conversation history so follow-up questions have context |
| `requirements.txt` | Python dependencies (`fastmcp`, `langchain`, `langchain-mcp-adapters`, `langchain-ollama`) |

## Notes / current limitations

This is a **learning-grade implementation** — read-only tools, minimal
input validation, no rate limiting or output redaction (pod logs and
`describe` output can contain sensitive values, and they are passed to
the LLM as-is). Because it runs against a local Ollama model, nothing
leaves your machine, but it's still built for local experimentation
against clusters you own, not for pointing at shared or production
infrastructure as-is.

Each `kubectl` call runs without a shell and has a 30-second timeout.
