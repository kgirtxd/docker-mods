# syntax=docker/dockerfile:1

FROM scratch

LABEL maintainer="username"

# copy local files
COPY root/ /
COPY --chmod=0755 root/etc/s6-overlay/s6-rc.d/init-mod-prowlarr-sync-download-clients-add-package/run /etc/s6-overlay/s6-rc.d/init-mod-prowlarr-sync-download-clients-add-package/run
COPY --chmod=0755 root/etc/s6-overlay/s6-rc.d/svc-mod-prowlarr-sync-download-clients/run /etc/s6-overlay/s6-rc.d/svc-mod-prowlarr-sync-download-clients/run
COPY --chmod=0755 root/usr/local/bin/prowlarr-sync-download-clients-loop /usr/local/bin/prowlarr-sync-download-clients-loop
COPY --chmod=0755 root/usr/local/bin/prowlarr-sync-download-clients.py /usr/local/bin/prowlarr-sync-download-clients.py
