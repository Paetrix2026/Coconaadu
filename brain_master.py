import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
import socketio
import os
import hashlib
import io
import base64
from typing import Optional
from PIL import Image  # Required for Swarm Mode Image Decomposition

app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

current_grid_secret = None
nodes = {}
swarm_enabled = False  # Global toggle for Swarm Mode

# --- SWARM MODE: IMAGE DECOMPOSITION LOGIC ---
class SwarmManager:
    def __init__(self):
        self.active_swarms = {}

    def split_image(self, image_bytes, rows=4, cols=4):
        """Step 3: Image Decomposition into a grid of tiles."""
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        tile_w, tile_h = w // cols, h // rows
        tiles = []

        for r in range(rows):
            for c in range(cols):
                # Calculate tile boundaries
                box = (c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)
                tile_img = img.crop(box)
                
                # Encode tile to base64 for transmission
                buf = io.BytesIO()
                tile_img.save(buf, format="JPEG")
                encoded_tile = base64.b64encode(buf.getvalue()).decode('utf-8')

                tiles.append({
                    "tile_id": len(tiles),
                    "row": r,
                    "col": c,
                    "image_data": encoded_tile,
                    "status": "pending"
                })
        return tiles, w, h

swarm_mgr = SwarmManager()

# --- STEP 1: TASK CLASSIFICATION SYSTEM ---
class TaskAnalyzer:
    def __init__(self):
        self.history = {} # Stores task_hash -> {type, time}

    def analyze(self, code):
        task_hash = hashlib.sha256(code.encode()).hexdigest()
        
        # A. Historical Database Check (Confidence 0.9)
        if task_hash in self.history:
            return self.history[task_hash]['type'], 0.9, "Historical Data Match"

        # B. Heuristic Code Analysis (Confidence 0.6)
        gpu_hints = ["torch", "tensorflow", "cuda", "cupy", "cv2.cuda"]
        cpu_hints = ["multiprocessing", "threading", "range(10**7)", "concurrent.futures"]
        io_hints = ["requests", "socket", "aiohttp", "boto3"]

        code_lower = code.lower()
        if any(h in code_lower for h in gpu_hints): return "gpu", 0.6, "GPU-specific libraries detected"
        if any(h in code_lower for h in cpu_hints): return "cpu", 0.6, "Heavy CPU patterns"
        if any(h in code_lower for h in io_hints): return "io", 0.6, "Network/API I/O patterns"
        
        return "balanced", 0.4, "General purpose logic detected"

    def get_task_hash(self, code):
        return hashlib.sha256(code.encode()).hexdigest()

analyzer = TaskAnalyzer()

# --- STEP 3 & 5: DYNAMIC SCORING ENGINE ---
def get_best_node(task_type):
    """Calculates the optimal node based on task profile and real-time telemetry."""
    weights = {
        "gpu":      {"w1":0.2, "w2":0.1, "w3":0.5, "w4":0.1, "w6":0.05},
        "cpu":      {"w1":0.5, "w2":0.2, "w3":0.1, "w4":0.1, "w6":0.05},
        "balanced": {"w1":0.3, "w2":0.2, "w3":0.3, "w4":0.1, "w6":0.05},
        "io":       {"w1":0.2, "w2":0.1, "w3":0.1, "w4":0.2, "w6":0.1}
    }
    w = weights.get(task_type, weights["balanced"])
    
    best_sid, best_score, best_reason = None, -1, ""

    for sid, n in nodes.items():
        if not n.get('verified'): continue
        
        # Scoring Algorithm
        raw_score = (w["w1"] * n.get('cpu_free', 0)) + \
                    (w["w2"] * n.get('ram_free', 0)) + \
                    (w["w3"] * n.get('gpu_free', 0)) + \
                    (w["w4"] * n.get('reliability_score', 1) * 100) - \
                    (w.get('w6', 0.05) * n.get('active_tasks', 0) * 10)
        
        # Effective Score (Penalty for busy nodes)
        eff_score = raw_score / (1 + n.get('active_tasks', 0))
        
        if eff_score > best_score:
            best_score, best_sid = eff_score, sid
            best_reason = f"Score: {round(eff_score, 2)} | Optimal for {task_type}"

    return best_sid, best_score, best_reason

# --- DASHBOARD & SOCKET EVENTS ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join("templates", "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@app.post("/set_session_key")
async def set_key(key: str = Form(...)):
    global current_grid_secret
    current_grid_secret = key
    for sid in nodes: nodes[sid]['verified'] = False
    return {"status": "Key Set"}

@app.post("/toggle_swarm")
async def toggle_swarm(state: bool = Form(...)):
    global swarm_enabled
    swarm_enabled = state
    print(f"🐝 SWARM MODE: {'ENABLED' if swarm_enabled else 'DISABLED'}")
    return {"swarm_mode": swarm_enabled}

@sio.on("node_stats")
async def handle_stats(sid, data):
    is_verified = (current_grid_secret is not None) and (data.get("auth_key") == current_grid_secret)
    if not is_verified and current_grid_secret and data.get("auth_key") != "":
        await sio.emit("force_reauth", {}, to=sid)
    
    if is_verified and not nodes.get(sid, {}).get('verified'):
        await sio.emit("notify_auth", {"name": data.get('name')})
    
    data['verified'] = is_verified
    nodes[sid] = data
    await sio.emit("node_stats_update", data)

@sio.on("script_result")
async def handle_result(sid, data):
    await sio.emit("dashboard_log", data)

@sio.on("stream_frame")
async def handle_stream(sid, data):
    await sio.emit("ui_update_frame", data)

# Step 6: Real-Time Swarm Streaming
@sio.on("tile_completed")
async def handle_tile_completion(sid, data):
    """Receive processed shard and relay to UI for reconstruction."""
    await sio.emit("tile_completed_ui", data)

@sio.on("task_complete_metrics")
async def handle_metrics(sid, data):
    task_hash = data.get('task_hash')
    if task_hash:
        analyzer.history[task_hash] = {
            "type": "gpu" if data.get('success') and data.get('gpu_peak', 0) > 30 else "cpu",
            "time": round(data.get('duration', 0), 2)
        }
    if not data.get('success'):
        # Step 6: Failure Handling
        nodes[sid]['reliability_score'] = max(0, nodes[sid].get('reliability_score', 1) - 0.1)

# --- THE SECURE INTELLIGENT DISPATCHER ---
async def universal_dispatch(script_code, node_id=None):
    if not current_grid_secret: return False
    
    task_type, conf, reason = analyzer.analyze(script_code)
    task_hash = analyzer.get_task_hash(script_code)

    target_sid = None
    if node_id:
        target_sid = next((s for s, n in nodes.items() if n['name'] == node_id), None)
    else:
        target_sid, score, reason = get_best_node(task_type)

    if target_sid:
        await sio.emit("execute_custom_script", {
            "code": script_code,
            "auth_key": current_grid_secret,
            "task_hash": task_hash
        }, to=target_sid)
        
        await sio.emit("dashboard_log", {
            "node": nodes[target_sid]['name'], 
            "output": f"🤖 [DELEGATOR]: Detected={task_type} -> Assigned to: {nodes[target_sid]['name']} ({reason})"
        })
        return True
    return False

# --- SWARM EXECUTION PIPELINE ---
@app.post("/upload_script")
async def upload_script(node_id: Optional[str] = Form(None), file: UploadFile = File(...)):
    """
    FIX 1: node_id is now Optional so the global upload button (no node selected) works.
    FIX 2: universal_dispatch argument order was swapped — now correctly (script_code, node_id).
    FIX 3: Swarm mode now actually dispatches tiles instead of returning an error.
    """
    content = await file.read()

    # --- IMAGE PATH: Always route through swarm pipeline ---
    # Images have no non-swarm execution path. The swarm_enabled toggle controls
    # the UI indicator only — image processing always uses distributed tile dispatch.
    if file.content_type.startswith("image/"):
        try:
            tiles, img_w, img_h = swarm_mgr.split_image(content)
            total_tiles = len(tiles)

            # Notify UI to set up swarm canvas
            await sio.emit("swarm_init", {
                "width": img_w,
                "height": img_h,
                "total_tiles": total_tiles
            })

            operation = "grayscale"  # Default operation; extend via Form field if needed

            # Distribute tiles across verified nodes in round-robin
            verified_sids = [sid for sid, n in nodes.items() if n.get('verified')]
            if not verified_sids:
                return {"status": "Error", "message": "No verified nodes available for swarm."}

            for i, tile in enumerate(tiles):
                target_sid = verified_sids[i % len(verified_sids)]
                await sio.emit("process_tile", {
                    "auth_key": current_grid_secret,
                    "tile_id": tile["tile_id"],
                    "row": tile["row"],
                    "col": tile["col"],
                    "image_data": tile["image_data"],
                    "operation": operation
                }, to=target_sid)

            return {"status": "Swarm dispatched", "tiles": total_tiles, "nodes": len(verified_sids)}
        except Exception as e:
            return {"status": "Error", "message": f"Swarm dispatch failed: {str(e)}"}

    try:
        # FIX 2: Correct argument order — script_code first, then node_id
        script_code = content.decode("utf-8")
        success = await universal_dispatch(script_code, node_id)
        return {"status": "Sent" if success else "Error: No session key set or no verified node found."}
    except UnicodeDecodeError:
        return {"status": "Error", "message": "Invalid script format (Binary detected)"}

# Legacy Endpoints maintained for compatibility
@app.post("/trigger_inventory")
async def trigger_inventory(node_id: Optional[str] = Form(None)):
    script = "import importlib.metadata, platform; print(f'--- SYSTEM: {platform.node()} ---'); [print(f\"{d.metadata['Name']}=={d.version}\") for d in importlib.metadata.distributions()]"
    await universal_dispatch(script, node_id)
    return {"status": "Success"}

@app.post("/check_network")
async def check_network(node_id: Optional[str] = Form(None)):
    script = "import time, socket; start=time.time(); socket.create_connection(('8.8.8.8', 53), timeout=2); print(f'Latency: {(time.time()-start)*1000:.2f}ms | Grid Status: SECURE')"
    await universal_dispatch(script, node_id)
    return {"status": "Testing"}

@app.post("/start_video_process")
async def start_video(node_id: Optional[str] = Form(None)):
    script = """
import cv2, base64, socketio, time, os
sio = socketio.Client()
try:
    sio.connect('http://100.79.119.87:5000') 
    cap = cv2.VideoCapture("test_video.mp4")
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        stream = cv2.resize(frame, (640, 360)); _, buf = cv2.imencode('.jpg', stream, [cv2.IMWRITE_JPEG_QUALITY, 30])
        sio.emit('stream_frame', {'node': os.environ.get('COMPUTERNAME'), 'frame': base64.b64encode(buf).decode('utf-8')})
        time.sleep(0.04)
    cap.release(); sio.disconnect()
except: pass
"""
    await universal_dispatch(script, node_id)
    return {"status": "Video Started"}

@app.post("/deploy")
async def global_deploy():
    script = "import platform; print(f'Deployment Successful on node: {platform.node()}')"
    status = [await universal_dispatch(script, nodes[sid]['name']) for sid in nodes if nodes[sid].get('verified')]
    return {"results": status}

if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)