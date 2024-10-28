import subprocess
import json
import os
import logging
import datetime
import signal
import sys
from prometheus_client import make_wsgi_app, Gauge
from flask import Flask
from waitress import serve
from shutil import which
from threading import Event

app = Flask("Speedtest-Exporter")

# Setup logging values
format_string = 'level=%(levelname)s datetime=%(asctime)s %(message)s'
logging.basicConfig(encoding='utf-8',
                   level=logging.INFO,  # Changed from DEBUG to INFO for performance
                   format=format_string)

# Disable Waitress Logs
log = logging.getLogger('waitress')
log.disabled = True

# Create Metrics
server = Gauge('speedtest_server_id', 'Speedtest server ID used to test')
jitter = Gauge('speedtest_jitter_latency_milliseconds', 'Speedtest current Jitter in ms')
ping = Gauge('speedtest_ping_latency_milliseconds', 'Speedtest current Ping in ms')
download_speed = Gauge('speedtest_download_bits_per_second', 'Speedtest current Download Speed in bit/s')
upload_speed = Gauge('speedtest_upload_bits_per_second', 'Speedtest current Upload speed in bits/s')
up = Gauge('speedtest_up', 'Speedtest status whether the scrape worked')

# Cache metrics for how long (seconds)?
cache_seconds = int(os.environ.get('SPEEDTEST_CACHE_FOR', 0))
cache_until = datetime.datetime.fromtimestamp(0)

# Shutdown handler
shutdown_event = Event()

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logging.info(f"Received signal {signum}. Starting graceful shutdown...")
    shutdown_event.set()
    # Give ongoing operations 5 seconds to complete
    sys.exit(0)

def bytes_to_bits(bytes_per_sec):
    return bytes_per_sec * 8

def bits_to_megabits(bits_per_sec):
    megabits = round(bits_per_sec * (10**-6), 2)
    return f"{megabits}Mbps"

def is_json(myjson):
    if not myjson:
        return False
    try:
        json.loads(myjson)
        return True
    except (ValueError, TypeError):
        return False

def runTest():
    if shutdown_event.is_set():
        return (0, 0, 0, 0, 0, 0)
        
    serverID = os.environ.get('SPEEDTEST_SERVER')
    timeout = int(os.environ.get('SPEEDTEST_TIMEOUT', 90))

    cmd = [
        "speedtest", "--format=json-pretty", "--progress=no",
        "--accept-license", "--accept-gdpr"
    ]
    if serverID:
        cmd.append(f"--server-id={serverID}")
    
    try:
        output = subprocess.check_output(cmd, timeout=timeout)
    except subprocess.CalledProcessError as e:
        logging.error(f'Speedtest CLI Error: {e}')
        return (0, 0, 0, 0, 0, 0)
    except subprocess.TimeoutExpired:
        logging.error('Speedtest CLI process timeout')
        return (0, 0, 0, 0, 0, 0)

    if not is_json(output):
        return (0, 0, 0, 0, 0, 0)

    try:
        data = json.loads(output)
        if "error" in data:
            logging.error(f'Speedtest error: {data["error"]}')
            return (0, 0, 0, 0, 0, 0)
        
        if data.get('type') == 'result':
            return (
                int(data['server']['id']),
                data['ping']['jitter'],
                data['ping']['latency'],
                bytes_to_bits(data['download']['bandwidth']),
                bytes_to_bits(data['upload']['bandwidth']),
                1
            )
    except (KeyError, TypeError) as e:
        logging.error(f'Error parsing speedtest result: {e}')
        return (0, 0, 0, 0, 0, 0)

    return (0, 0, 0, 0, 0, 0)

@app.route("/metrics")
def updateResults():
    global cache_until

    if datetime.datetime.now() > cache_until:
        r_server, r_jitter, r_ping, r_download, r_upload, r_status = runTest()
        server.set(r_server)
        jitter.set(r_jitter)
        ping.set(r_ping)
        download_speed.set(r_download)
        upload_speed.set(r_upload)
        up.set(r_status)
        
        if r_status:  # Only log if test was successful
            logging.info(f"Server={r_server} Jitter={r_jitter}ms Ping={r_ping}ms Download={bits_to_megabits(r_download)} Upload={bits_to_megabits(r_upload)}")

        cache_until = datetime.datetime.now() + datetime.timedelta(seconds=cache_seconds)

    return make_wsgi_app()

@app.route("/")
def mainPage():
    return ("<h1>Welcome to Speedtest-Exporter.</h1>" +
            "Click <a href='/metrics'>here</a> to see metrics.")

def checkForBinary():
    speedtest_path = which("speedtest")
    if not speedtest_path:
        logging.error("Speedtest CLI binary not found. Please install it from https://www.speedtest.net/apps/cli")
        sys.exit(1)
        
    try:
        version_output = subprocess.check_output(['speedtest', '--version'], text=True)
        if "Speedtest by Ookla" not in version_output:
            raise ValueError("Unofficial speedtest CLI detected")
    except (subprocess.SubprocessError, ValueError) as e:
        logging.error(f"Speedtest CLI verification failed: {e}")
        logging.error("Please install the official CLI from https://www.speedtest.net/apps/cli")
        sys.exit(1)

if __name__ == '__main__':
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        checkForBinary()
        PORT = int(os.getenv('SPEEDTEST_PORT', 9798))
        logging.info(f"Starting Speedtest-Exporter on http://0.0.0.0:{PORT}")
        
        serve(app, host='0.0.0.0', port=PORT, threads=4, _quiet=True)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)
