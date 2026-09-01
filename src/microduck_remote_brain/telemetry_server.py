# ruff: noqa: E501
from __future__ import annotations

import argparse
import base64
import json
import socket
import threading
import time
from collections.abc import Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DASHBOARD = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MicroDuck telemetry</title><style>
:root{color-scheme:dark;font:14px system-ui,sans-serif}body{margin:0;background:#10151b;color:#e8edf2}main{max-width:1200px;margin:auto;padding:20px}h1{font-size:22px;margin:0 0 4px}p{color:#aab6c2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.card{background:#19212a;border:1px solid #30404e;border-radius:8px;padding:14px}.video{grid-column:span 2}h2{font-size:15px;margin:0 0 12px;color:#72d6c9}.camera{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:#050708}.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{background:#111820;padding:8px}.metric b{display:block;font-size:18px}.metric small{color:#93a3b1}.joints{display:grid;grid-template-columns:1fr 1fr;gap:5px}.joint{display:flex;justify-content:space-between;background:#111820;padding:5px 7px}.tof{display:grid;grid-template-columns:repeat(8,1fr);gap:3px}.zone{aspect-ratio:1;display:grid;place-items:center;font-size:10px;color:#061014;border-radius:2px}.muted{color:#aab6c2}.ok{color:#72d6c9}.warning{color:#f4bf68}code{color:#b9d9ff}@media(max-width:700px){.video{grid-column:span 1}}
</style></head><body><main><h1>MicroDuck · télémétrie</h1><p id="updated">Connexion...</p><section class="grid"><article class="card video"><h2>Caméra tête</h2><img class="camera" src="/api/camera/stream" alt="Flux de la caméra tête du MicroDuck"><p class="muted">Vue embarquée fournie par la source de simulation active.</p></article><article class="card"><h2>État du robot</h2><div id="metrics" class="metrics"></div></article><article class="card"><h2>IMU</h2><div id="imu" class="metrics"></div></article><article class="card"><h2>Articulations</h2><div id="joints" class="joints"></div></article><article class="card"><h2>ToF / lidar 8×8</h2><div id="tof" class="tof"></div><p class="muted">Distances en mm, mise à jour à 15 Hz selon le modèle du VL53L5CX.</p></article></section></main><script>
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metric=(name,value,unit='')=>`<div class="metric"><small>${esc(name)}</small><b>${esc(value)} <small>${esc(unit)}</small></b></div>`;
async function checked(path){const response=await fetch(path,{cache:'no-store'});if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.error||`HTTP ${response.status}`)}return response.json()}
async function refresh(){try{const [state,tof]=await Promise.all([checked('/api/state'),checked('/api/tof')]);const imu=state.imu||{};
document.querySelector('#updated').innerHTML='<span class="ok">Connecté</span> · sim_time '+Number(state.sim_time||0).toFixed(2)+' s · trunk '+(state.trunk||[]).map(x=>Number(x).toFixed(3)).join(', ');
document.querySelector('#metrics').innerHTML=[metric('Trunk Z',Number(state.trunk_z||0).toFixed(3),'m'),metric('Tension',Number(state.volts||7.4).toFixed(2),'V'),metric('Vitesse X',Number((state.base_velocity||[0])[0]||0).toFixed(3),'m/s'),metric('Température',Number((state.temps_c||[32])[0]||32).toFixed(1),'°C')].join('');
document.querySelector('#imu').innerHTML=[metric('Gravité', (imu.gravity||[]).map(x=>Number(x).toFixed(2)).join(', ')),metric('Gyroscope',(imu.gyro||[]).map(x=>Number(x).toFixed(2)).join(', ')),metric('Quaternion',(imu.quat||[]).map(x=>Number(x).toFixed(2)).join(', '))].join('');
document.querySelector('#joints').innerHTML=(state.positions||[]).map((v,i)=>`<div class="joint"><span>J${i}</span><code>${Number(v).toFixed(3)} rad</code></div>`).join('');
const values=tof.distance_mm||[], max=Math.max(1,...values);document.querySelector('#tof').innerHTML=values.map((v,i)=>{const ratio=v?Math.min(1,v/max):0;const color=v?`hsl(${Math.round(190-190*ratio)},80%,60%)`:'#394550';return `<div class="zone" title="zone ${i}: ${v||'no target'} mm" style="background:${color}">${v?Math.round(v):'·'}</div>`}).join('');
}catch(error){document.querySelector('#updated').innerHTML='<span class="warning">Déconnecté : '+esc(error)+'</span>'}}
refresh();setInterval(refresh,500);
</script></body></html>"""


MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def read_simulator(host: str, port: int, operation: str) -> dict[str, object]:
    with socket.create_connection((host, port)) as connection:
        stream = connection.makefile("rw", encoding="utf-8", newline="\n")
        stream.write(
            json.dumps(
                {"op": "hello", "protocol": 1, "joints": 15}, allow_nan=False
            )
            + "\n"
        )
        stream.flush()
        if _read_response(stream).get("protocol") != 1:
            raise RuntimeError("simulator protocol mismatch")
        stream.write(json.dumps({"op": operation}, allow_nan=False) + "\n")
        stream.flush()
        answer = _read_response(stream)
        if "error" in answer:
            raise RuntimeError(str(answer["error"]))
        return answer


def _read_response(stream: object) -> dict[str, object]:
    line = stream.readline(MAX_RESPONSE_BYTES + 1)  # type: ignore[attr-defined]
    if not line or len(line.encode("utf-8")) > MAX_RESPONSE_BYTES or not line.endswith("\n"):
        raise RuntimeError("simulator response exceeds the framing limit")
    try:
        answer = json.loads(line, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise RuntimeError("simulator returned invalid JSON") from error
    if not isinstance(answer, dict):
        raise RuntimeError("simulator response must be an object")
    return answer


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def read_state(host: str, port: int) -> dict[str, object]:
    state = read_simulator(host, port, "read")
    state.update(read_simulator(host, port, "slow"))
    return state


def read_camera(host: str, port: int) -> bytes:
    frame = read_simulator(host, port, "camera")
    encoded = frame.get("jpeg_base64")
    if not isinstance(encoded, str):
        raise RuntimeError("simulator camera response has no JPEG frame")
    return base64.b64decode(encoded, validate=True)


class SimulatorCache:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._lock = threading.Lock()
        self._values: dict[str, tuple[float, object]] = {}
        self.last_success: float | None = None
        self.last_error: str | None = None

    def get(self, key: str, maximum_age: float) -> object:
        now = time.monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and now - cached[0] <= maximum_age:
                return cached[1]
            try:
                if key == "state":
                    value: object = read_state(self._host, self._port)
                elif key == "camera":
                    value = read_camera(self._host, self._port)
                else:
                    value = read_simulator(self._host, self._port, key)
            except (OSError, RuntimeError, ValueError) as error:
                self.last_error = str(error)
                raise
            self._values[key] = (now, value)
            self.last_success = now
            self.last_error = None
            return value


class Handler(BaseHTTPRequestHandler):
    simulator_host = "127.0.0.1"
    simulator_port = 7801
    cache = SimulatorCache(simulator_host, simulator_port)

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/":
                self._send(200, "text/html; charset=utf-8", DASHBOARD.encode())
            elif self.path == "/api/state":
                self._send_json(self.cache.get("state", 0.1))
            elif self.path == "/api/tof":
                self._send_json(self.cache.get("tof", 0.1))
            elif self.path == "/api/camera.jpg":
                jpeg = self.cache.get("camera", 0.08)
                if not isinstance(jpeg, bytes):
                    raise RuntimeError("camera cache returned an invalid frame")
                self._send(200, "image/jpeg", jpeg)
            elif self.path == "/api/camera/stream":
                self._stream_camera()
            elif self.path == "/api/health":
                self.cache.get("state", 0.5)
                self._send_json({"status": "ok", "simulator": "connected"})
            else:
                self._send_json({"error": "not found"}, 404)
        except (OSError, RuntimeError, ValueError) as error:
            self._send_json({"error": str(error)}, 503)

    def _send_json(self, value: object, status: int = 200) -> None:
        self._send(status, "application/json", json.dumps(value, allow_nan=False).encode())

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream_camera(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                jpeg = self.cache.get("camera", 0.08)
                if not isinstance(jpeg, bytes):
                    raise RuntimeError("camera cache returned an invalid frame")
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError, OSError, RuntimeError, ValueError):
            pass

    def log_message(self, format: str, *args: object) -> None:  # pylint: disable=redefined-builtin
        del format, args


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Web telemetry dashboard for a MicroDuck simulator"
    )
    parser.add_argument("--simulator-host", default="127.0.0.1")
    parser.add_argument("--simulator-port", type=int, default=7801)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8780)
    args = parser.parse_args(argv)
    Handler.simulator_host = args.simulator_host
    Handler.simulator_port = args.simulator_port
    Handler.cache = SimulatorCache(args.simulator_host, args.simulator_port)
    with ThreadingHTTPServer((args.listen_host, args.listen_port), Handler) as server:
        print(f"telemetry dashboard listening on {args.listen_host}:{args.listen_port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
