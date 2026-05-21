"""Kubernetes cluster health for the Health tab.

Queries the k8s API for pod status, resource usage, and component mapping.
Works when running inside a k8s cluster (in-cluster config) or falls back
to kubeconfig for local dev.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Map pod name prefixes to app components
_COMPONENT_MAP = {
    "api": {"component": "Backend API", "icon": "🔧"},
    "frontend": {"component": "Frontend UI", "icon": "🖥"},
    "postgres": {"component": "Database", "icon": "🗄"},
    "opensearch": {"component": "Search Engine", "icon": "🔍"},
    "bookstack-db": {"component": "BookStack DB", "icon": "💾"},
    "bookstack": {"component": "Document Wiki", "icon": "📚"},
    "minio": {"component": "Object Storage", "icon": "📦"},
    "worker": {"component": "Background Worker", "icon": "⚙"},
}


def get_cluster_health() -> dict:
    """Get pod status and resource usage from the k8s cluster.

    Returns:
        {
            "available": true/false,
            "pods": [{name, component, status, restarts, age, cpu, memory, node}],
            "summary": {total, running, pending, failed}
        }
    """
    try:
        from kubernetes import client, config

        # Try in-cluster first, fall back to kubeconfig
        try:
            config.load_incluster_config()
        except config.ConfigException:
            kubeconfig = os.getenv("KUBECONFIG", "/etc/rancher/k3s/k3s.yaml")
            config.load_kube_config(config_file=kubeconfig)

        # kubernetes client v36 has auth issues with k3s in-cluster config.
        # Build a properly configured ApiClient manually.
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        if os.path.exists(token_path):
            with open(token_path) as f:
                token = f.read().strip()
            cfg = client.Configuration()
            cfg.host = f"https://{os.getenv('KUBERNETES_SERVICE_HOST', '10.43.0.1')}:{os.getenv('KUBERNETES_SERVICE_PORT', '443')}"
            cfg.api_key = {"BearerToken": f"Bearer {token}"}
            cfg.ssl_ca_cert = ca_path
            cfg.verify_ssl = True
            api_client = client.ApiClient(cfg)
        else:
            api_client = client.ApiClient()

        v1 = client.CoreV1Api(api_client)
        namespace = os.getenv("K8S_NAMESPACE", "docsearch")

        # Get pods
        pods = v1.list_namespaced_pod(namespace=namespace)
        pod_list = []

        for pod in pods.items:
            name = pod.metadata.name
            phase = pod.status.phase

            # Map to component
            comp_info = {"component": "Unknown", "icon": "❓"}
            for prefix, info in _COMPONENT_MAP.items():
                if name.startswith(prefix):
                    comp_info = info
                    break

            # Container status
            restarts = 0
            ready = False
            if pod.status.container_statuses:
                cs = pod.status.container_statuses[0]
                restarts = cs.restart_count
                ready = cs.ready or False

            # Age
            age = ""
            if pod.metadata.creation_timestamp:
                from datetime import datetime, timezone

                delta = datetime.now(timezone.utc) - pod.metadata.creation_timestamp
                if delta.days > 0:
                    age = f"{delta.days}d"
                elif delta.seconds > 3600:
                    age = f"{delta.seconds // 3600}h"
                else:
                    age = f"{delta.seconds // 60}m"

            # Resource requests/limits from spec
            cpu_req = ""
            mem_req = ""
            if pod.spec.containers:
                resources = pod.spec.containers[0].resources
                if resources and resources.requests:
                    cpu_req = resources.requests.get("cpu", "")
                    mem_req = resources.requests.get("memory", "")

            # Disk: check if pod has volume mounts with PVCs
            disk = ""
            if pod.spec.volumes:
                for vol in pod.spec.volumes:
                    if vol.persistent_volume_claim:
                        pvc_name = vol.persistent_volume_claim.claim_name
                        try:
                            pvc = v1.read_namespaced_persistent_volume_claim(
                                pvc_name,
                                namespace,
                            )
                            storage = pvc.spec.resources.requests.get("storage", "")
                            disk = f"{pvc_name} ({storage})"
                        except Exception:
                            disk = pvc_name
                        break

            # Image metadata (tag, hash, build date)
            image_info = ""
            image_id = ""
            if pod.status.container_statuses:
                cs = pod.status.container_statuses[0]
                image_info = cs.image or ""
                image_id = (cs.image_id or "").replace("docker-pullable://", "").replace("docker://", "")

            pod_list.append(
                {
                    "name": name,
                    "component": comp_info["component"],
                    "icon": comp_info["icon"],
                    "status": phase,
                    "ready": ready,
                    "restarts": restarts,
                    "age": age,
                    "cpu": cpu_req,
                    "memory": mem_req,
                    "disk": disk,
                    "node": pod.spec.node_name or "",
                    "image": image_info,
                    "image_hash": image_id,
                    "started_at": pod.status.start_time.strftime("%Y-%m-%d %H:%M:%S")
                    if pod.status.start_time
                    else "",
                },
            )

        # Get events for each pod (only for the current pod name)
        try:
            events = v1.list_namespaced_event(namespace=namespace)
            for p in pod_list:
                pod_events = []
                for ev in events.items:
                    if not ev.involved_object:
                        continue
                    obj_name = ev.involved_object.name or ""
                    # Only match events for THIS exact pod
                    if obj_name == p["name"]:
                        ts = ""
                        if ev.last_timestamp:
                            ts = ev.last_timestamp.strftime("%H:%M:%S")
                        elif ev.event_time:
                            ts = ev.event_time.strftime("%H:%M:%S")
                        pod_events.append(
                            {
                                "time": ts,
                                "type": ev.type or "",
                                "reason": ev.reason or "",
                                "message": (ev.message or "")[:120],
                            },
                        )
                # Most recent first, limit to 20
                p["events"] = sorted(
                    pod_events,
                    key=lambda x: x["time"],
                    reverse=True,
                )[:20]
        except Exception:
            pass  # nosec B110

        # Try to get metrics (requires metrics-server)
        try:
            custom_api = client.CustomObjectsApi(api_client)
            metrics = custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
            )
            for item in metrics.get("items", []):
                pod_name = item["metadata"]["name"]
                for p in pod_list:
                    if p["name"] == pod_name:
                        containers = item.get("containers", [])
                        if containers:
                            p["cpu_usage"] = (
                                containers[0]
                                .get("usage", {})
                                .get(
                                    "cpu",
                                    "",
                                )
                            )
                            p["memory_usage"] = (
                                containers[0]
                                .get("usage", {})
                                .get(
                                    "memory",
                                    "",
                                )
                            )
        except Exception:
            pass  # nosec B110 - metrics-server may not be available

        # Summary
        summary = {
            "total": len(pod_list),
            "running": sum(1 for p in pod_list if p["status"] == "Running"),
            "pending": sum(1 for p in pod_list if p["status"] == "Pending"),
            "failed": sum(1 for p in pod_list if p["status"] in ("Failed", "CrashLoopBackOff")),
        }

        return {"available": True, "pods": pod_list, "summary": summary}

    except Exception as e:
        logger.warning("k8s health check failed: %s", e)
        return {
            "available": False,
            "error": str(e),
            "pods": [],
            "summary": {"total": 0, "running": 0, "pending": 0, "failed": 0},
        }
