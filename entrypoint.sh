#!/bin/bash
# Entrypoint for the LlavaVision CUDA container

MODEL_REPO=${MODEL_REPO:-"https://huggingface.co/mys/ggml_bakllava-1/resolve/main/"}
MODEL=${MODEL:-"ggml-model-q4_k.gguf"}
MMPROJ=${MMPROJ:-"mmproj-model-f16.gguf"}
NLG=${NLG:-"35"}
TS=${TS:-"100,0"} # For GPU-only, single GPU
TUNNEL=${TUNNEL:-"false"}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-5000}
GENERATE_CERTS=${GENERATE_CERTS:-"false"}
CERT_SUBJ=${CERT_SUBJ:-"/C=AU/ST=VIC/O=MyOrg, Inc./CN=llavavision.local"}
DEBUG=${DEBUG:-""} # set to '--debug' to enable debug mode

function startFlask() {
  cd /app/llavavision || exit
  # --key key.pem --cert cert.pem
  flask run --host="$HOST" --port "$PORT" "$DEBUG" &
  llavaVisionPid=$!
}

function startLlama() {
  /app/llama/build/bin/server -m "/app/models/${MODEL}" --mmproj "/app/models/${MMPROJ}" -ngl "$NLG" -ts "$TS"
  llamaPid=$!
}

function downloadModel() {
  cd /app/models || exit
  # download the models if they don't exist
  if [ -f "$MODEL" ]; then
    echo "Model exists"
  else
    aria2c --split=4 --always-resume=true --enable-http-pipelining=true --http-accept-gzip=true --max-connection-per-server=6 --auto-file-renaming=false "${MODEL_REPO}${MODEL}" --out "$MODEL"
  fi

  if [ -f "$MMPROJ" ]; then
    echo "MMProj exists"
  else
    aria2c --split=4 --always-resume=true --enable-http-pipelining=true --http-accept-gzip=true --max-connection-per-server=6 --auto-file-renaming=false "${MODEL_REPO}${MMPROJ}" --out "$MMPROJ"
  fi
}

function genCerts() {
  if [ "$GENERATE_CERTS" == "true" ]; then
    cd /app/llavavision || exit

    # Check if dummy certs exist, if not, create them
    if [ ! -f "cert.pem" ]; then
      echo "Generating certs"

      openssl req -newkey rsa:4096 -x509 -sha256 -days 365 -nodes -out cert.pem -keyout key.pem -subj "$CERT_SUBJ"
    fi
  else
    echo "Not generating certs"
  fi
}

function tunnel() {
  if [ "$TUNNEL" == "true" ]; then
    echo "Tunnelling enabled"
    cd /app/llavavision || exit
    #
    npx localtunnel --local-https --allow_invalid_cert ---port "$PORT" &
    tunnelPid=$!
  else
    echo "Tunnelling disabled"
    return
  fi

}
function cleanup() {
  kill "$llavaVisionPid"
  kill "$llamaPid"
  kill "$tunnelPid"
}

trap cleanup EXIT

downloadModel
genCerts
startFlask
startLlama
tunnel

wait
