from fastmcp import FastMCP
import subprocess
import os

mcp = FastMCP("Kubernetes MCP Server")

# Set by the agent at startup via environment variables (see k8s_agent_mcp.py).
# Falls back to sane defaults if the server is ever run standalone.
DEFAULT_CONTEXT = os.environ.get("K8S_CONTEXT", "")       # "" = use kubeconfig's current-context
DEFAULT_NAMESPACE = os.environ.get("K8S_NAMESPACE", "default")


def run_kubectl(args: list[str], context: str = "") -> str:
    """Helper to run a kubectl command safely, scoped to a specific cluster context."""
    ctx = context or DEFAULT_CONTEXT
    full_args = ["kubectl"]
    if ctx:
        full_args += ["--context", ctx]
    full_args += args

    try:
        result = subprocess.run(full_args, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: kubectl command timed out after 30s."
    except FileNotFoundError:
        return "Error: kubectl not found. Is it installed and on PATH?"


@mcp.tool
def get_current_context() -> str:
    """
    Show which cluster (kubeconfig context) and namespace this session
    is currently targeting. Use this if the user asks "which cluster
    am I on" or before running anything ambiguous.
    """
    ctx = DEFAULT_CONTEXT or run_kubectl(["config", "current-context"])
    return f"Cluster context: {ctx}\nDefault namespace: {DEFAULT_NAMESPACE}"


@mcp.tool
def list_available_contexts() -> str:
    """
    List all Kubernetes cluster contexts available in the local kubeconfig.
    Use this if the user asks what clusters they can switch to.
    """
    return run_kubectl(["config", "get-contexts"])


@mcp.tool
def list_available_namespaces(context: str = "") -> str:
    """
    List all namespaces available in the given cluster context.
    Use this if the user asks what namespaces exist, or before running
    a tool against a namespace you're unsure exists.

    Args:
        context: Cluster context to check. Leave empty to use the
            session's default cluster.
    """
    return run_kubectl(["get", "namespaces"], context=context)


@mcp.tool
def list_pods(namespace: str = "", all_namespaces: bool = False, context: str = "") -> str:
    """
    List pods and their status (Running, CrashLoopBackOff, Pending, etc).

    Use this first when the user asks what's going on in the cluster,
    which pods are unhealthy, or to find the exact pod name needed for
    other tools like logs or describe.

    Args:
        namespace: Namespace to list pods from. Leave empty to use the
            session's default namespace.
        all_namespaces: If True, ignores `namespace` and lists pods across
            the whole cluster. Use when the user doesn't specify a
            namespace or asks "what's broken anywhere".
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    ns = namespace or DEFAULT_NAMESPACE
    args = ["get", "pods", "-o", "wide"]
    args += ["--all-namespaces"] if all_namespaces else ["-n", ns]
    return run_kubectl(args, context=context)


@mcp.tool
def describe_pod(pod_name: str, namespace: str = "", context: str = "") -> str:
    """
    Show full details of a pod: containers, image, resource limits,
    volumes, node assignment, and — most importantly — the Events section
    at the bottom (OOMKilled, ImagePullBackOff, FailedScheduling, etc).

    Use this for root cause analysis (RCA) when a pod isn't Running,
    is stuck Pending, or is restarting repeatedly.

    Args:
        pod_name: Exact name of the pod (get it from list_pods first if unsure).
        namespace: Namespace the pod lives in. Leave empty to use the
            session's default namespace.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    if not pod_name.strip():
        return "Error: pod_name is required."
    ns = namespace or DEFAULT_NAMESPACE
    return run_kubectl(["describe", "pod", pod_name.strip(), "-n", ns], context=context)


@mcp.tool
def get_pod_logs(
    pod_name: str,
    namespace: str = "",
    container: str = "",
    previous: bool = False,
    tail_lines: int = 200,
    context: str = "",
) -> str:
    """
    Fetch logs from a pod (or a specific container in a multi-container pod).

    Use this to debug application-level errors, exceptions, or crash reasons.
    Set previous=True when the pod is currently in CrashLoopBackOff and you
    need the logs from BEFORE the last restart.

    Args:
        pod_name: Exact name of the pod.
        namespace: Namespace the pod lives in. Leave empty to use the
            session's default namespace.
        container: Specific container name, required only if the pod has
            more than one container.
        previous: If True, fetch logs from the previous (crashed) container
            instance instead of the current one.
        tail_lines: Number of most recent log lines to return. Defaults to 200.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    if not pod_name.strip():
        return "Error: pod_name is required."

    ns = namespace or DEFAULT_NAMESPACE
    args = ["logs", pod_name.strip(), "-n", ns, "--tail", str(tail_lines)]
    if container.strip():
        args += ["-c", container.strip()]
    if previous:
        args += ["--previous"]

    return run_kubectl(args, context=context)


@mcp.tool
def get_events(namespace: str = "", all_namespaces: bool = False, context: str = "") -> str:
    """
    Show recent cluster events sorted by time (scheduling failures, pulls,
    OOM kills, volume mount errors, etc).

    Args:
        namespace: Namespace to check. Leave empty to use the session's
            default namespace.
        all_namespaces: If True, shows events across all namespaces.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    ns = namespace or DEFAULT_NAMESPACE
    args = ["get", "events", "--sort-by=.lastTimestamp"]
    args += ["--all-namespaces"] if all_namespaces else ["-n", ns]
    return run_kubectl(args, context=context)


@mcp.tool
def list_deployments(namespace: str = "", context: str = "") -> str:
    """
    List deployments and their ready/available replica counts.

    Args:
        namespace: Namespace to list deployments from. Leave empty to
            use the session's default namespace.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    ns = namespace or DEFAULT_NAMESPACE
    return run_kubectl(["get", "deployments", "-n", ns, "-o", "wide"], context=context)


@mcp.tool
def describe_deployment(deployment_name: str, namespace: str = "", context: str = "") -> str:
    """
    Show full details and rollout status of a deployment.

    Args:
        deployment_name: Exact name of the deployment.
        namespace: Namespace the deployment lives in. Leave empty to use
            the session's default namespace.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    if not deployment_name.strip():
        return "Error: deployment_name is required."
    ns = namespace or DEFAULT_NAMESPACE
    return run_kubectl(["describe", "deployment", deployment_name.strip(), "-n", ns], context=context)


@mcp.tool
def get_rollout_history(deployment_name: str, namespace: str = "", context: str = "") -> str:
    """
    Show revision history of a deployment.

    Args:
        deployment_name: Exact name of the deployment.
        namespace: Namespace the deployment lives in. Leave empty to use
            the session's default namespace.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    if not deployment_name.strip():
        return "Error: deployment_name is required."
    ns = namespace or DEFAULT_NAMESPACE
    return run_kubectl(["rollout", "history", f"deployment/{deployment_name.strip()}", "-n", ns], context=context)


@mcp.tool
def get_resource_usage(namespace: str = "", all_namespaces: bool = False, context: str = "") -> str:
    """
    Show live CPU/memory usage per pod (requires metrics-server).

    Args:
        namespace: Namespace to check. Leave empty to use the session's
            default namespace.
        all_namespaces: If True, shows usage across all namespaces.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    ns = namespace or DEFAULT_NAMESPACE
    args = ["top", "pods"]
    args += ["--all-namespaces"] if all_namespaces else ["-n", ns]
    return run_kubectl(args, context=context)


@mcp.tool
def get_services(namespace: str = "", context: str = "") -> str:
    """
    List services and their type, cluster IP, and exposed ports.

    Args:
        namespace: Namespace to list services from. Leave empty to use
            the session's default namespace.
        context: Cluster context to target. Leave empty to use the
            session's default cluster.
    """
    ns = namespace or DEFAULT_NAMESPACE
    return run_kubectl(["get", "svc", "-n", ns, "-o", "wide"], context=context)


if __name__ == "__main__":
    mcp.run()