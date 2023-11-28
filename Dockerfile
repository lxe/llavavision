# Dockerfile for building LlavaVision
ARG UBUNTU_VERSION=22.04
ARG CUDA_VERSION=12.2.2
ARG BASE_CUDA_DEV_CONTAINER=nvidia/cuda:${CUDA_VERSION}-devel-ubuntu${UBUNTU_VERSION}
ARG RUNTIME_CUDA_CONTAINER=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu${UBUNTU_VERSION}
FROM ${BASE_CUDA_DEV_CONTAINER} as build

ENV CUDA_DOCKER_ARCH=${CUDA_DOCKER_ARCH:-x86_64}
ENV LLAMA_CUBLAS=1


RUN apt-get update && \
  apt-get install -y build-essential python3 python3-pip git git-lfs wget aria2 \
  python-is-python3 python3.10-venv nvidia-cuda-toolkit cmake && \
  rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/ggerganov/llama.cpp /app/llama && \
  rm -rf /app/llama/.git

WORKDIR /app/llama

RUN mkdir build && \
  cd build && \
  cmake .. -DLLAMA_CUBLAS=ON && \
  cmake --build . --config Release && \
  cmake --install .

RUN pip install --upgrade pip setuptools wheel \
  && pip install -r requirements.txt

RUN git clone --depth=1 https://github.com/lxe/llavavision /app/llavavision && \
  rm -rf /app/llavavision/.git

WORKDIR /app/llavavision

RUN pip install -r requirements.txt

COPY entrypoint.sh /app/entrypoint.sh

FROM ${RUNTIME_CUDA_CONTAINER} as runtime

ENV UID=${UID:-1001}
WORKDIR /app/llavavision

# Drop root privileges
RUN useradd -m -d /app -u $UID app
USER app

COPY --chown=app:app --from=build /usr/local /usr/local
COPY --chown=app:app --from=build /app /app

VOLUME [ "/app/models" ]

CMD ["/app/entrypoint.sh"]
