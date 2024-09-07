#!/bin/bash

# Build the Docker image
docker build -t granular-sampler .

# Run the Docker container
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix -v $(pwd)/samples:/app/samples granular-sampler
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    IP=$(ifconfig en0 | grep inet | awk '$1=="inet" {print $2}')
    xhost + $IP
    docker run -it --rm -e DISPLAY=$IP:0 -v /tmp/.X11-unix:/tmp/.X11-unix -v $(pwd)/samples:/app/samples granular-sampler
else
    # Windows (assuming WSL2)
    export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0
    docker run -it --rm -e DISPLAY=$DISPLAY -v $(pwd)/samples:/app/samples granular-sampler
fi
