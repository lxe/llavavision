import json
import os
from flask import Flask, request, jsonify, render_template, Response
import requests
import base64

app = Flask(__name__)

VISION_BACKEND = os.environ.get("VISION_BACKEND", "llamacpp")
LLAMACPP_URL = os.environ.get("LLAMACPP_URL", "http://localhost:8080/completion")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7")
MINIMAX_API_URL = "https://api.minimax.io/v1/chat/completions"


def describe_with_llamacpp(encoded_string):
    image_data = [{"data": encoded_string, "id": 12}]
    data = {
        "prompt": "USER:[img-12]Describe the image briefly and accurately.\nASSISTANT:",
        "n_predict": 128,
        "image_data": image_data,
        "stream": True,
    }
    headers = {"Content-Type": "application/json"}
    response = requests.post(LLAMACPP_URL, headers=headers, json=data, stream=True)

    def generate():
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                try:
                    chunk_json = json.loads(chunk.decode().split("data: ")[1])
                    content = chunk_json.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError):
                    continue

    return Response(generate(), content_type="text/plain")


def describe_with_minimax(encoded_string):
    if not MINIMAX_API_KEY:
        return Response("MINIMAX_API_KEY not configured", status=500, content_type="text/plain")

    # Clamp temperature to MiniMax's valid range (0.0, 1.0]
    temperature = max(0.01, min(float(os.environ.get("MINIMAX_TEMPERATURE", "0.7")), 1.0))

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": MINIMAX_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded_string}"},
                    },
                    {"type": "text", "text": "Describe the image briefly and accurately."},
                ],
            }
        ],
        "stream": True,
        "temperature": temperature,
        "max_tokens": 128,
    }
    response = requests.post(MINIMAX_API_URL, headers=headers, json=data, stream=True)

    def generate():
        for line in response.iter_lines():
            if line and line.startswith(b"data: "):
                payload = line[6:]
                if payload == b"[DONE]":
                    break
                try:
                    chunk_json = json.loads(payload)
                    delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

    return Response(generate(), content_type="text/plain")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/describe", methods=["POST"])
def describe():
    encoded_string = request.json["image"]
    if VISION_BACKEND == "minimax":
        return describe_with_minimax(encoded_string)
    return describe_with_llamacpp(encoded_string)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
