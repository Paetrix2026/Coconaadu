import uvicorn
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse
import socketio
import os
import base64

app = FastAPI()
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, app)

nodes = {}

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    with open(os.path.join("templates", "index.html"), "r", encoding="utf-8") as f:
        return f.read()

@sio.event
async def connect(sid, environ):
    print(f"📡 Node connected: {sid}")

@sio.event
async def disconnect(sid):
    if sid in nodes:
        del nodes[sid]

@sio.on("node_stats")
async def handle_stats(sid, data):
    nodes[sid] = data
    await sio.emit("node_stats_update", data)

@sio.on("script_result")
async def handle_result(sid, data):
    await sio.emit("dashboard_log", data)

@app.post("/trigger_inventory")
async def trigger_inventory(node_id: str = Form(...)):
    inventory_script = """
import importlib.metadata, platform, sys
print(f"--- SYSTEM: {platform.node()} ---")
packages = sorted([f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions()])
for p in packages: print(p)
"""
    target_sid = next((sid for sid, n in nodes.items() if n['name'] == node_id), None)
    if target_sid:
        await sio.emit("execute_custom_script", {"code": inventory_script}, to=target_sid)
        return {"status": "Success"}
    return {"status": "Error"}

@app.post("/check_network")
async def check_network(node_id: str = Form(...)):
    network_script = """
import time, platform, socket
print(f"--- NETWORK REPORT: {platform.node()} ---")
start = time.time()
try:
    socket.create_connection(("8.8.8.8", 53), timeout=2)
    latency = (time.time() - start) * 1000
    print(f"Grid-to-WAN Latency: {latency:.2f}ms")
    print("Status: MESH STABLE")
except Exception as e:
    print(f"Network Check Failed: {e}")
"""
    target_sid = next((sid for sid, n in nodes.items() if n['name'] == node_id), None)
    if target_sid:
        await sio.emit("execute_custom_script", {"code": network_script}, to=target_sid)
        return {"status": "Testing"}
    return {"status": "Error"}

@app.post("/deploy")
async def deploy_yolo():
    if not nodes: return {"status": "Error"}
    best_sid = min(nodes.keys(), key=lambda k: nodes[k]['gpu_temp'])
    await sio.emit("run_task", {"image": "ultralytics/ultralytics:latest"}, to=best_sid)
    return {"status": "Success", "node": nodes[best_sid]['name']}

@app.post("/upload_script")
async def upload_script(node_id: str = Form(...), file: UploadFile = File(...)):
    content = await file.read()
    script_text = content.decode("utf-8")
    target_sid = next((sid for sid, n in nodes.items() if n['name'] == node_id), None)
    if target_sid:
        await sio.emit("execute_custom_script", {"code": script_text}, to=target_sid)
        return {"status": "Sent"}
    return {"status": "Error"}




# Add this event handler inside your brain_master.py
@sio.on("stream_frame")
async def handle_stream(sid, data):
    # data contains {'node': 'Omen', 'frame': 'base64_string'}
    # We broadcast this directly to the web dashboard
    await sio.emit("ui_update_frame", data)

@app.post("/start_video_process")
async def start_video(node_id: str = Form(...)):
    # This script tells the muscle to open a video and start sending frames
    video_script = """
import cv2
import base64
import socketio
import time

sio = socketio.SimpleClient()
sio.connect('http://100.79.119.87:5000') # YOUR BRAIN IP

# Use 0 for Webcam or a path to a 4K mp4 file
cap = cv2.VideoCapture(0) 

while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break
    
    # 4K is heavy, so we resize for the stream but process at high res
    # Here you could add: frame = cv2.GaussianBlur(frame, (15,15), 0)
    
    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
    jpg_as_text = base64.b64encode(buffer).decode('utf-8')
    
    sio.emit('stream_frame', {'node': 'target', 'frame': jpg_as_text})
    time.sleep(0.03) # ~30 FPS

cap.release()
sio.disconnect()
"""
    # For the demo, we'll just send this as a custom script trigger
    target_sid = next((sid for sid, n in nodes.items() if n['name'] == node_id), None)
    if target_sid:
        await sio.emit("execute_custom_script", {"code": video_script}, to=target_sid)
        return {"status": "Streaming Started"}


if __name__ == "__main__":
    uvicorn.run(socket_app, host="0.0.0.0", port=5000)