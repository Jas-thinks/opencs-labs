# OpenCS Labs — backend upstream pool.
#
# This is the single place backend addresses are defined. nginx.conf includes
# it; no routing rule hardcodes a host. Regenerate when backend membership
# changes (deploy/scripts/render_upstreams.sh).
#
# Addresses are the container-network IPs measured in Phase 0 on the shared
# host 10.1.75.53 (see docs/deployment/INFRASTRUCTURE_INVENTORY.md). They are
# stable for the lifetime of these containers but are NOT static assignments;
# re-measure after any container recreation.

upstream opencs_backends {
    # Round-robin (nginx default), NOT least_conn.
    #
    # Measured on this deployment: least_conn + keepalive pins nearly all
    # traffic to a single peer (72/76 requests to one backend, 1 each to the
    # others), because with low concurrency every peer has zero active
    # connections and the pooled keepalive connection to the first peer keeps
    # winning the tie. Round-robin distributes deterministically and is
    # trivial to reason about when a peer is removed from rotation.
    #
    # NOTE: no `keepalive` directive here. Upstream keepalive pools one
    # connection per worker and reuses it for every request, which re-pins all
    # traffic to whichever peer the pool connected to first — verified on this
    # deployment (9/9 requests to one backend with keepalive enabled, even
    # round-robin and `curl --no-keepalive`). Connection setup on the docker
    # bridge is cheap; even distribution matters more.
    #
    # With one uvicorn worker per container and three containers, this gives
    # 3-way parallelism; raise workers only if the 512 MiB cgroup cap allows.
    server 172.17.0.61:8000 max_fails=3 fail_timeout=15s;   # stu87_sys2
    server 172.17.0.57:8000 max_fails=3 fail_timeout=15s;   # stu87_sys3
    server 172.17.0.39:8000 max_fails=3 fail_timeout=15s;   # stu87_sys4
}
