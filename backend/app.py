# Import necessary libraries
from flask import Flask, jsonify
from pymongo.mongo_client import MongoClient
import pymongo
import json
from bson import ObjectId
from gpiozero import DistanceSensor
from gpiozero import MotionSensor
from time import sleep
import time
import RPi.GPIO as GPIO
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Global constant variables for GPIO pins and MongoDB URI
trigPin = 23
echoPin = 24
uri = os.getenv("MONGO_URI")

# Initialize Flask app
app = Flask(__name__)

# Constants for application logic
DISTANCE = 0.5  # Average distance threshold (in meters)
SLEEP = 2       # Sleep duration between sensor checks (in seconds)
COMPLETE = False  # Flag to know when the end button is pushed

# Function to get the last recorded statistic from MongoDB
def get_last_stat():
    latestStat = stats_db.find_one(sort=[('ID', pymongo.DESCENDING)])
    return latestStat

# Custom JSON encoder class to handle MongoDB ObjectId
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

# Create a new MongoClient and connect to the MongoDB server
client = MongoClient(uri, tls=True, tlsAllowInvalidCertificates=True)

# Connect to MongoDB cluster and specific database and collection
cluster = client['player_data']
stats_db = cluster['stats']

# Flask route to start the sensor monitoring and data recording
@app.route("/start", methods=["GET"])
def start():
    # Initialize distance and vibration sensors
    distance_sensor = DistanceSensor(echoPin, trigPin)
    vibration_sensor = MotionSensor(16, threshold=0.01)

    # Retrieve the latest statistic
    latestStat = get_last_stat()
    latestId = latestStat['ID']

    # Initialize the stat dictionary for the current session
    start_time = time.time()
    stat = {'ID': latestId + 1, 'shotsTaken': 0, 'shotsMade': 0, 'shotsMissed': 0,
            'highestStreak': 0, 'streak': 0, 'date': time.ctime(),
            'timeOfSession': 0, 'status': 'active'}
    filter = {'ID': stat['ID']}

    # Insert the new stat record into MongoDB
    stats_db.insert_one(stat)

    # Variables to keep track of the last sensor activations
    last_distance_time = -1
    last_vibration_time = -1

    # Main loop for monitoring sensors and updating stats
    while not COMPLETE:
        # Check and update distance sensor
        if last_distance_time < 0 or (time.time() - last_distance_time) > SLEEP:
            last_distance_time = -1
            if distance_sensor.distance < DISTANCE / 2:
                last_distance_time = time.time()
                stat['shotsMade'] += 1
                stat['streak'] += 1
                print('Successful shot taken')

        # Check and update vibration sensor
        if last_vibration_time < 0 or (time.time() - last_vibration_time) > SLEEP:
            last_vibration_time = -1
            if vibration_sensor.motion_detected:
                last_vibration_time = time.time()
                stat['shotsTaken'] += 1
                print('Unsuccessful shot taken')

        # Update the session duration and calculate missed shots
        stat['timeOfSession'] = time.time() - start_time
        stat['shotsMissed'] = stat['shotsTaken'] - stat['shotsMade']

        # Prepare the update for MongoDB
        newvalues = {"$set": {"shotsTaken": stat['shotsTaken'], "shotsMade": stat['shotsMade'],
                              "shotsMissed": stat['shotsMissed'], "streak": stat['streak'],
                              "highestStreak": stat['highestStreak'], "timeOfSession": stat['timeOfSession']}}

        # Update the highest streak and reset streak on a missed shot
        missed = stat['shotsMissed']
        if stat['highestStreak'] < stat['streak']:
            stat['highestStreak'] = stat['streak']
        if missed > lastMiss:
            stat['streak'] = 0
            lastMiss = missed

        # Update the stat record in MongoDB
        stats_db.update_one(filter, newvalues)
        sleep(0.1)

    # Reset the COMPLETE flag and clean up GPIO resources
    COMPLETE = False
    GPIO.cleanup()

# Flask route to retrieve player statistics
@app.route('/player-stats', methods=['GET'])
def player_stats():
    # Fetch all documents from MongoDB
    data = stats_db.find()
    data_list = []
    for document in data:
        data_list.append(document)

    # Convert data to JSON and return
    json_string = json.dumps(data_list, cls=CustomJSONEncoder)
    return json_string

# Flask route to end the current session
@app.route('/end', methods=['GET'])
def end():
    global COMPLETE
    COMPLETE = True

    # Update the last statistic to mark as complete
    latestStat = get_last_stat()
    filter = {'ID': latestStat['ID']}
    newvalues = {"$set": {"status": "complete"}}

    stats_db.update_one(filter, newvalues)
    return jsonify({"Message": "Terminating, Function"})

# Clean up GPIO resources
GPIO.cleanup()

# Run the Flask app if this script is executed directly
if __name__ == '__main__':
    app.run(debug=True)



