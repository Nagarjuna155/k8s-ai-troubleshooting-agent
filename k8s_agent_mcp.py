import asyncio
import os
import subprocess
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from langchain_ollama import ChatOllama

SYSTEM_PROMPT = """You are a Kubernetes troubleshooting assistant.
You are already scoped to a specific cluster context and default
namespace chosen by the user at session start — do not ask for these
again unless the user explicitly wants to check a different one.

When a user reports an issue:
1. If they don't name a specific pod/deployment, start broad — check
   list_pods, get_events, or list_deployments.
2. Once you find a problem pod, use describe_pod for scheduling/resource
   errors (check the Events section), and get_pod_logs for
   application-level errors.
3. If a pod is CrashLoopBackOff, fetch logs with previous=True.
4. If it looks like a bad rollout, check get_rollout_history and
   describe_deployment.
5. Always end with a concise root cause summary and a suggested next
   action. Be specific and cite exact pod/container names and error
   strings you found in tool output — don't guess.
"""


def run_cmd(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout.strip()


def choose_context() -> str:
    """List kubeconfig contexts and let the user pick one, or use current default."""
    raw = run_cmd(["kubectl", "config", "get-contexts", "-o", "name"])
    contexts = [c for c in raw.splitlines() if c.strip()]

    if not contexts:
        print("No kubeconfig contexts found. Using kubectl's current default.")
        return ""

    current = run_cmd(["kubectl", "config", "current-context"])

    print("\nAvailable cluster contexts:")
    for i, ctx in enumerate(contexts, 1):
        marker = "  (current)" if ctx == current else ""
        print(f"  {i}. {ctx}{marker}")

    while True:
        choice = input(f"\nSelect a cluster [1-{len(contexts)}] (Enter for current: {current}): ").strip()
        if choice == "":
            return current
        if choice.isdigit() and 1 <= int(choice) <= len(contexts):
            return contexts[int(choice) - 1]
        print("Invalid choice, try again.")


def choose_namespace(context: str) -> str:
    """List namespaces in the chosen context and let the user pick one."""
    args = ["kubectl"]
    if context:
        args += ["--context", context]
    args += ["get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"]

    raw = run_cmd(args)
    namespaces = raw.split()

    if not namespaces:
        print("Could not list namespaces (check cluster connectivity). Defaulting to 'default'.")
        return "default"

    print("\nAvailable namespaces:")
    for i, ns in enumerate(namespaces, 1):
        marker = "  (default)" if ns == "default" else ""
        print(f"  {i}. {ns}{marker}")

    while True:
        choice = input(f"\nSelect a namespace [1-{len(namespaces)}] (Enter for 'default'): ").strip()
        if choice == "":
            return "default" if "default" in namespaces else namespaces[0]
        if choice.isdigit() and 1 <= int(choice) <= len(namespaces):
            return namespaces[int(choice) - 1]
        print("Invalid choice, try again.")


async def main():
    print("Kubernetes Troubleshooting Assistant — session setup\n")

    selected_context = choose_context()
    selected_namespace = choose_namespace(selected_context)

    print(f"\nUsing cluster: {selected_context or '(kubeconfig default)'}")
    print(f"Using default namespace: {selected_namespace}\n")

    # Pass the selection into the MCP server subprocess via env vars
    client = MultiServerMCPClient(
        {
            "k8s-mcp": {
                "transport": "stdio",
                "command": "python",
                "args": ["k8s_mcp_server.py"],
                "env": {
                    **os.environ,
                    "K8S_CONTEXT": selected_context,
                    "K8S_NAMESPACE": selected_namespace,
                },
            }
        }
    )

    tools = await client.get_tools()

    llm = ChatOllama(
        model="gemma4:26b",
        temperature=0.8,
    )

    agent = create_agent(llm, tools, system_prompt=SYSTEM_PROMPT)

    print("Ask about pods, deployments, logs, events, or RCA.")
    print("Type 'exit' or 'quit' to stop.\n")

    conversation = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break

        conversation.append({"role": "user", "content": user_input})

        try:
            response = await agent.ainvoke({"messages": conversation})
        except Exception as e:
            print(f"[Error while processing request: {e}]\n")
            continue

        ai_message = response["messages"][-1]
        print(f"\nAssistant: {ai_message.content}\n")

        conversation = response["messages"]


if __name__ == "__main__":
    asyncio.run(main())