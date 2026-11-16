# OpenCS Labs -- JupyterHub control plane.
#
# Runs the Hub, the configurable HTTP proxy, the OpenCS authenticator and the
# idle culler. Notebook servers are separate pods/containers; this image only
# orchestrates them.
FROM jupyterhub/jupyterhub:4.1.5

# KubeSpawner is the production spawner; DockerSpawner (OPENCE_SPAWNER=docker)
# is the single-host Compose path. Idle culling is a JupyterHub-managed service
# (see jupyterhub_config.py). PyJWT is what opencs_auth.py validates session
# tokens with.
RUN pip install --no-cache-dir \
        jupyterhub-kubespawner==5.0.0 \
        dockerspawner==13.0.0 \
        jupyterhub-idle-culler==1.2.1 \
        PyJWT==2.10.1

COPY jupyterhub_config.py opencs_auth.py /srv/jupyterhub/

WORKDIR /srv/jupyterhub

EXPOSE 8081

# 8081 is the Hub API/logical port; the proxy (configurable-http-proxy) listens
# on 8000 in front of it. Both are inside the container.
CMD ["jupyterhub", "-f", "/srv/jupyterhub/jupyterhub_config.py"]
