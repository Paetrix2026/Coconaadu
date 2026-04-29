import socketio, GPUtil, psutil, docker, time, socket, os, subprocess
from docker.types import DeviceRequest

BRAIN_IP = "http://100.79.119.87:5000" # Asus Tailscale IP
MY_HOSTNAME = socket.gethostname()
OUTPUT_PATH = "C:\\grid_results"
if not os.path.exists(OUTPUT_PATH): os.makedirs(OUTPUT_PATH)

sio = socketio.Client()
client = docker.from_env()

@sio.event
def connect(): print(f"✅ Connected as {MY_HOSTNAME}")

@sio.on("run_task")
def on_run_task(data):
    try:
        gpu_request = DeviceRequest(count=-1, capabilities=[['gpu']])
        container = client.containers.run(
            data['image'], 
            "yolo predict model=yolov8n.pt source='https://ultralytics.com/images/bus.jpg' save=True project='/runs' name='predict'", 
            device_requests=[gpu_request],
            volumes={os.path.abspath(OUTPUT_PATH): {'bind': '/runs', 'mode': 'rw'}},
            detach=True
        )
        print(f"🚀 AI Container {container.short_id} Started.")
    except Exception as e: print(f"❌ Docker Error: {e}")

@sio.on("execute_custom_script")
def on_custom_script(data):
    with open("temp_task.py", "w") as f: f.write(data['code'])
    print(f"🏃 Executing custom script from Brain...")
    try:
        res = subprocess.run(["python", "temp_task.py"], capture_output=True, text=True, timeout=30)
        output = res.stdout if res.returncode == 0 else res.stderr
        sio.emit("script_result", {"node": MY_HOSTNAME, "output": output.strip()})
    except Exception as e:
        sio.emit("script_result", {"node": MY_HOSTNAME, "output": f"Failed: {str(e)}"})

while True:
    try:
        if not sio.connected: sio.connect(BRAIN_IP)
        gpus = GPUtil.getGPUs()
        sio.emit("node_stats", {
            "name": MY_HOSTNAME,
            "gpu_temp": gpus[0].temperature if gpus else 0,
            "vram_free": gpus[0].memoryFree if gpus else 0,
            "cpu_usage": psutil.cpu_percent()
        })
        time.sleep(2)
    except: time.sleep(5)