"""Read-only ComfyUI progress for the local MV worker."""
import asyncio
import json
import threading
from urllib.parse import urlencode, urlsplit


class LiveProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self._connection = "connecting"
        self._task = {}
        self._job_id = None
        self._nodes = {}

    def start(self, comfy_url, client_id):
        threading.Thread(target=self._run, args=(comfy_url, client_id), daemon=True).start()

    def queued(self, job_id, prompt_id, graph):
        with self._lock:
            self._job_id = job_id
            self._nodes = {str(key): node.get("class_type", "") for key, node in graph.items()}
            self._task = {"prompt_id": prompt_id, "state": "queued"}

    def snapshot(self, job_id):
        with self._lock:
            if self._job_id != job_id or self._connection != "connected":
                return None
            if self._task.get("state") != "running" or "max" not in self._task:
                return None
            return {key: self._task[key] for key in ("node", "value", "max")}

    def clear(self, job_id):
        with self._lock:
            if self._job_id == job_id:
                self._job_id = None
                self._task = {}
                self._nodes = {}

    def _set_connection(self, state):
        with self._lock:
            self._connection = state
            if state != "connected":
                self._task.pop("max", None)

    def receive(self, message):
        event, data = message.get("type"), message.get("data")
        if not isinstance(data, dict) or not data.get("prompt_id"):
            return
        with self._lock:
            task = self._task
            if data["prompt_id"] != task.get("prompt_id"):
                return
            if event == "execution_start":
                task["state"] = "running"
            elif event == "executing":
                if data.get("node") is None:
                    if task["state"] not in ("failed", "interrupted"):
                        task["state"] = "finished"
                else:
                    self._set_node(str(data["node"]))
            elif event == "progress":
                node_id = str(data.get("node"))
                value, maximum = data.get("value"), data.get("max")
                if type(value) is not int or type(maximum) is not int or not 0 <= value <= maximum or maximum == 0:
                    return
                if node_id != task.get("node_id"):
                    self._set_node(node_id)
                    task = self._task
                task.update(value=value, max=maximum)
            elif event == "execution_success":
                task["state"] = "finished"
            elif event in ("execution_error", "execution_interrupted"):
                task["state"] = "failed" if event == "execution_error" else "interrupted"

    def _set_node(self, node_id):
        self._task = {
            "prompt_id": self._task["prompt_id"], "state": "running",
            "node_id": node_id, "node": self._nodes.get(node_id, ""),
        }

    def _run(self, comfy_url, client_id):
        try:
            import aiohttp
        except ImportError:
            self._set_connection("unavailable")
            return
        asyncio.run(self._listen(aiohttp, comfy_url, client_id))

    async def _listen(self, aiohttp, comfy_url, client_id):
        base = urlsplit(comfy_url)
        url = base._replace(scheme="wss" if base.scheme == "https" else "ws",
                            path=base.path.rstrip("/") + "/ws",
                            query=urlencode({"clientId": client_id}), fragment="").geturl()
        timeout = aiohttp.ClientTimeout(total=None, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    async with session.ws_connect(url, heartbeat=15) as socket:
                        self._set_connection("connected")
                        async for frame in socket:
                            if frame.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    message = json.loads(frame.data)
                                except ValueError:
                                    continue
                                if isinstance(message, dict):
                                    self.receive(message)
                except (aiohttp.ClientError, TimeoutError, OSError):
                    pass
                self._set_connection("connecting")
                await asyncio.sleep(2)
