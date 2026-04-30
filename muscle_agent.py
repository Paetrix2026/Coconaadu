import socketio
import psutil
import platform
import subprocess
import time
import os
import threading
import io
import base64
from PIL import Image

# Try to import GPUtil for real-time hardware-level GPU metrics
try:
    import GPUtil
except ImportError:
    GPUtil = None

# --- CONFIG ---
BRAIN_IP = "http://100.79.119.87:5000" 
MY_HOSTNAME = platform.node()
GRID_SECRET = "" 
is_prompting = False
active_tasks_count = 0  # Dynamic penalty for Intelligent Delegation
reliability_score = 1.0  # Quality of Service (QoS) metric

sio = socketio.Client()

def get_stats():
    """
    Step 2: Enhanced Node Metrics Collection
    Reports high-fidelity telemetry to the Brain for the Scoring Algorithm.
    """
    cpu_usage = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    
    # Default GPU fallback
    gpu_usage, gpu_free, vram_available = 0, 100, 4096
    
    if GPUtil:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu = gpus[0]
                gpu_usage = gpu.load * 100
                gpu_free = 100 - gpu_usage
                vram_available = gpu.memoryFree
        except Exception:
            pass

    return {
        "name": MY_HOSTNAME,
        "cpu_usage": cpu_usage,
        "cpu_free": 100 - cpu_usage,
        "ram_usage": ram.percent,
        "ram_free": 100 - ram.percent,
        "gpu_usage": gpu_usage,
        "gpu_free": gpu_free,
        "vram_available": vram_available,
        "active_tasks": active_tasks_count,
        "reliability_score": reliability_score,
        "auth_key": GRID_SECRET 
    }

def ask_for_key(prompt_text="\n🔑 ENTER ACTIVE SESSION KEY: "):
    global GRID_SECRET, is_prompting
    is_prompting = True
    GRID_SECRET = input(prompt_text).strip()
    is_prompting = False
    print("🛰️ Key updated. Resume heartbeat...")

@sio.event
def connect():
    print(f"\n✅ LINK ESTABLISHED: {MY_HOSTNAME} connected to Brain.")

@sio.on("force_reauth")
def on_reauth(data):
    global is_prompting
    if not is_prompting:
        print("\n🛑 AUTH ERROR: Key expired or session changed.")
        threading.Thread(target=ask_for_key, args=("🔄 ENTER NEW SESSION CODE: ",)).start()

# --- SWARM MODE: PARALLEL COMPUTE ENGINE ---
@sio.on("process_tile")
def on_process_tile(data):
    """
    Step 5: Parallel Execution on Nodes
    Decompresses image shards, applies operations, and streams back in real-time.
    """
    global active_tasks_count
    if data.get("auth_key") != GRID_SECRET: return

    try:
        active_tasks_count += 1
        start_time = time.time()

        # 1. Decode incoming Shard
        img_bytes = base64.b64decode(data['image_data'])
        img = Image.open(io.BytesIO(img_bytes))

        # 2. Heuristic Operation Selection
        op = data.get('operation', 'grayscale')
        if op == "grayscale":
            img = img.convert("L")
        elif op == "edges":
            from PIL import ImageFilter
            img = img.filter(ImageFilter.FIND_EDGES)
        elif op == "blur":
            from PIL import ImageFilter
            img = img.filter(ImageFilter.GaussianBlur(radius=2))

        # 3. Re-encode Result
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        processed_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        # 4. Stream back to Master for Reconstruction
        sio.emit("tile_completed", {
            "tile_id": data['tile_id'],
            "row": data['row'],
            "col": data['col'],
            "image_data": "data:image/jpeg;base64," + processed_b64,
            "node": MY_HOSTNAME,
            "exec_time": round(time.time() - start_time, 4)
        })
        active_tasks_count = max(0, active_tasks_count - 1)
    except Exception as e:
        active_tasks_count = max(0, active_tasks_count - 1)
        print(f"🐝 Swarm Processing Error: {e}")

# --- CUSTOM SCRIPT DISPATCHER ---
@sio.on("execute_custom_script")
def on_custom_script(data):
    global active_tasks_count
    if data.get("auth_key") != GRID_SECRET:
        sio.emit("script_result", {"node": MY_HOSTNAME, "output": "🛑 AUTH FAILURE: Key Mismatch"})
        return

    sio.emit("script_result", {"node": MY_HOSTNAME, "output": "🔑 [HANDSHAKE]: Verified. Executing..."})

    try:
        active_tasks_count += 1
        start_time = time.time()
        
        # Save payload to local disk
        with open("temp_task.py", "w", encoding="utf-8") as f:
            f.write(data['code'])
        
        # Smart Logic: Identify long-running or background tasks
        script_content = data['code'].lower()
        if any(x in script_content for x in ["cv2", "videocapture", "while true", "time.sleep(0."]):
            subprocess.Popen(["python", "temp_task.py"], shell=True)
            sio.emit("script_result", {"node": MY_HOSTNAME, "output": "🚀 Async background process launched."})
            active_tasks_count = max(0, active_tasks_count - 1)
        else:
            # Standard Console execution with timeout
            res = subprocess.run(["python", "temp_task.py"], capture_output=True, text=True, timeout=30)
            duration = time.time() - start_time
            
            # Send results to Dashboard
            sio.emit("script_result", {"node": MY_HOSTNAME, "output": res.stdout or res.stderr or "✅ Execution Finished."})
            
            # Step 7: Feedback Loop for Learning System
            sio.emit("task_complete_metrics", {
                "node": MY_HOSTNAME, 
                "task_hash": data.get("task_hash", "unknown"),
                "duration": duration, 
                "success": res.returncode == 0
            })
            active_tasks_count = max(0, active_tasks_count - 1)
    except Exception as e:
        active_tasks_count = max(0, active_tasks_count - 1)
        sio.emit("script_result", {"node": MY_HOSTNAME, "output": f"❌ OS Error: {str(e)}"})

if __name__ == "__main__":
    print("\n" + "█"*50)
    print(" SOVEREIGN GRID : PARALLEL AGENT v5.5 ")
    print("█"*50)
    
    if not GPUtil:
        print("⚠️  Warning: GPUtil missing. Real-time GPU telemetry disabled.")

    threading.Thread(target=ask_for_key).start()

    try:
        sio.connect(BRAIN_IP)
        while True:
            if sio.connected:
                # Real-time Telemetry Heartbeat
                sio.emit("node_stats", get_stats())
            time.sleep(2)
    except Exception as e:
        print(f"Criticial Connection Failure: {e}")