from flask import Flask, jsonify
from pymongo.mongo_client import MongoClient
import pymongo
import json
from bson import ObjectId
from gpiozero import DistanceSensor, MotionSensor
from threading import Thread
from time import sleep
import time
import RPi.GPIO as GPIO
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
uri = os.getenv("MONGO_URI")

# GPIO pins
TRIG_PIN = 23
ECHO_PIN = 24
VIBE_PIN = 16

# App constants
DISTANCE_THRESHOLD = 0.5  # meters
SENSOR_INTERVAL = 2       # seconds between distance/vibration checks

# Shared flag & thread handle
COMPLETE = False
monitor_thread = None

# Flask setup
app = Flask(__name__)

# MongoDB setup
client = MongoClient(uri, tls=True, tlsAllowInvalidCertificates=True)
cluster = client['player_data']
stats_db = cluster['stats']

# Custom JSON encoder for ObjectId
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

def get_last_stat():
    return stats_db.find_one(sort=[('ID', pymongo.DESCENDING)]) or {'ID': 0}

def monitor_loop():
    global COMPLETE
    # Initialize sensors
    distance_sensor = DistanceSensor(ECHO_PIN, TRIG_PIN)
    vibration_sensor = MotionSensor(VIBE_PIN, threshold=0.01)

    # Build initial stat record
    latest = get_last_stat()
    new_id = latest['ID'] + 1
    start_time = time.time()
    stat = {
        'ID': new_id,
        'shotsTaken': 0,
        'shotsMade': 0,
        'shotsMissed': 0,
        'highestStreak': 0,
        'streak': 0,
        'date': time.ctime(),
        'timeOfSession': 0,
        'status': 'active'
    }
    stats_db.insert_one(stat)
    record_filter = {'ID': new_id}

    # Timing trackers
    last_dist_time = -1
    last_vibe_time = -1
    last_miss_count = 0

    # Main loop
    while not COMPLETE:
        now = time.time()

        # Distance sensor check
        if last_dist_time < 0 or (now - last_dist_time) > SENSOR_INTERVAL:
            last_dist_time = -1
            if distance_sensor.distance < (DISTANCE_THRESHOLD / 2):
                last_dist_time = now
                stat['shotsMade'] += 1
                stat['streak'] += 1
                stat['shotsTaken'] += 1
                print("Successful shot detected")

        # Vibration sensor check
        if last_vibe_time < 0 or (now - last_vibe_time) > SENSOR_INTERVAL:
            last_vibe_time = -1
            if vibration_sensor.motion_detected:
                last_vibe_time = now
                stat['shotsTaken'] += 1
                print("Unsuccessful shot detected")

        # Update session metrics
        stat['timeOfSession'] = now - start_time
        stat['shotsMissed'] = stat['shotsTaken'] - stat['shotsMade']

        # Update highest streak
        if stat['streak'] > stat['highestStreak']:
            stat['highestStreak'] = stat['streak']

        # Reset streak if a new miss occurred
        if stat['shotsMissed'] > last_miss_count:
            stat['streak'] = 0
            last_miss_count = stat['shotsMissed']

        # Push updates to MongoDB
        update_fields = {
            "shotsTaken": stat['shotsTaken'],
            "shotsMade": stat['shotsMade'],
            "shotsMissed": stat['shotsMissed'],
            "streak": stat['streak'],
            "highestStreak": stat['highestStreak'],
            "timeOfSession": stat['timeOfSession']
        }
        stats_db.update_one(record_filter, {"$set": update_fields})

        sleep(0.1)

    # Clean up once COMPLETE is True
    GPIO.cleanup()

@app.route("/start", methods=["GET"])
def start():
    global COMPLETE, monitor_thread
    if monitor_thread and monitor_thread.is_alive():
        return jsonify({"error": "Session already running"}), 409

    COMPLETE = False
    monitor_thread = Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()
    return jsonify({"message": "Monitoring started"}), 202

@app.route("/end", methods=["GET"])
def end():
    global COMPLETE
    COMPLETE = True

    # Mark the last record as complete
    latest = get_last_stat()
    stats_db.update_one({'ID': latest['ID']}, {"$set": {"status": "complete"}})
    return jsonify({
        "Code": 200,
        "Message": "Session successfully terminated."
    }), 200

@app.route("/player-stats", methods=["GET"])
def player_stats():
    # Fetch all stats and return as JSON
    docs = list(stats_db.find())
    return json.dumps(docs, cls=CustomJSONEncoder), 200, {"Content-Type": "application/json"}

if __name__ == "__main__":
    app.run(debug=True)
