"""Optional, private gateway. Only this service has access to the Docker socket.

It executes RadioFlix's standalone driver as the existing recording user, never
rfriends' initializers, web UI, or arbitrary client-provided commands.
"""
import base64
import hmac
import http.client
import json
import os
import socket
import struct
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from radioflix.schemas.reservations import Broadcast

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Job(Broadcast):
    id: str = Field(pattern=r"^[a-f0-9]{32}$")


class Operation(BaseModel):
    operation: Literal["create", "inspect", "cancel"]
    job: Job


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(os.getenv("RFRIENDS_DOCKER_SOCKET", "/var/run/docker.sock"))


def docker_request(path, payload=None):
    connection = DockerConnection("localhost", timeout=35)
    try:
        connection.request("POST" if payload is not None else "GET", path,
                           json.dumps(payload).encode() if payload is not None else None,
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        data = response.read(2_000_001)
        if response.status >= 300 or len(data) > 2_000_000:
            raise ValueError("Docker request failed")
        return data
    finally:
        connection.close()


def run_driver(operation):
    config = {
        "base": os.getenv("RFRIENDS_BASE", "/home/user/rfriends3"),
        "tmp": os.getenv("RFRIENDS_TMP", "/home/user/tmp"),
        "queue": os.getenv("RFRIENDS_QUEUE", "a"),
    }
    source = Path(__file__).with_name("rfriends_driver.php").read_text().removeprefix("<?php\n")
    argument = base64.b64encode(json.dumps({**operation, "config": config}).encode()).decode()
    container = quote(os.getenv("RFRIENDS_CONTAINER", "rfriends3"), safe="")
    command = {"AttachStdout": True, "AttachStderr": True, "Tty": False,
               "User": os.getenv("RFRIENDS_USER", "user"),
               "Cmd": ["php", "-d", "display_errors=0", "-d", "log_errors=0", "-r", source, argument]}
    exec_id = json.loads(docker_request(f"/containers/{container}/exec", command))["Id"]
    output = docker_request(f"/exec/{exec_id}/start", {"Detach": False, "Tty": False})
    stdout = bytearray()
    while output:
        if len(output) < 8:
            raise ValueError("incomplete Docker response")
        stream, size = output[0], struct.unpack(">I", output[4:8])[0]
        if len(output) < 8 + size:
            raise ValueError("incomplete Docker frame")
        if stream == 1:
            stdout.extend(output[8:8 + size])
        output = output[8 + size:]
    status = json.loads(docker_request(f"/exec/{exec_id}/json"))
    if status.get("Running") or status.get("ExitCode") != 0:
        raise ValueError("driver failed")
    return json.loads(stdout)


@app.post("/execute")
def execute(request: Operation, authorization: str = Header(default="")):
    try:
        secret = Path(os.environ["RFRIENDS_TOKEN_FILE"]).read_text().strip()
    except (OSError, KeyError):
        raise HTTPException(503, detail={"code": "unconfigured"}) from None
    if len(secret) < 32 or not hmac.compare_digest(authorization, "Bearer " + secret):
        raise HTTPException(403, detail={"code": "authentication"})
    if request.operation != "inspect" and os.getenv("RFRIENDS_ENABLE_WRITES") != "1":
        raise HTTPException(409, detail={"code": "writes_disabled"})
    try:
        result = run_driver(request.model_dump(mode="json"))
        if not isinstance(result, dict):
            raise ValueError("invalid response")
        if "error" in result:
            code = result["error"]
            if code not in {"conflict", "too_late", "incompatible", "ownership"}:
                code = "unknown"
            raise HTTPException(409 if code != "unknown" else 502, detail={"code": code})
        if result.get("state") not in {"scheduled", "running", "elapsed", "cancelled", "absent"}:
            raise ValueError("invalid state")
        return result
    except (OSError, ValueError, KeyError, http.client.HTTPException):
        # Never return Docker output, paths, environment variables or PHP diagnostics.
        raise HTTPException(502, detail={"code": "unknown"}) from None
