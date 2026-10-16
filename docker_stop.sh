#!/usr/bin/env bash
docker run --network host \
        --name regserver \
        --restart unless-stopped \
        --mount type=bind,source=/var/snap/docker/common/regeserver/etc,target=/etc/regserver \
        --mount type=bind,source=/var/snap/docker/common/regeserver/log,target=/var/log \
	--detach \
        regserver
