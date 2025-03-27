from flask import Flask, request, jsonify
import threading
import logging
from datetime import datetime

from config.config import get_config
from core.factory import ChannelProcessorFactory
from config.database import get_mongo_client

app = Flask(__name__)
config = get_config()

# Create a factory to generate the appropriate processor based on channel type
channel_factory = ChannelProcessorFactory()

def get_channel_type(db, channel_id):
    channel_map = {}
    channels = db.channel_ids.find({})
    
    for channel in channels:
        if channel_id in channel["channel_id"]:
            channel_map[channel_id] = channel["channel_name"].lower().replace("_channel", "")
    
    return channel_map.get(channel_id, "unknown")


def handle_event(event, channel_type):
    with app.app_context():
        
        processor = channel_factory.get_processor(channel_type)
        if not processor:
            logging.error(f"No processor found for channel type: {channel_type}")
            return
        
        processor.process_event(event)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json
    
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})
    
    mongo_client = get_mongo_client()
    db = mongo_client["hrbp"]
    
    if "event" in data:
        event = data["event"]
        channel_id = event.get("channel", "")
        print(channel_id)
        
        channel = get_channel_type(db, channel_id)
        print("Channel fetched : ", channel)

        threading.Thread(target=handle_event, args=(event, channel)).start()
        
    return jsonify({"status": "OK"}), 200

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("Starting Flask server...")

    mongo_client = get_mongo_client()
    db = mongo_client["hrbp"]
    
    for processor_type in ["leave", "git", "jira"]:
        processor = channel_factory.get_processor(processor_type)
        if processor:
            processor.initialize_database()
            processor.sync_data()
    
    app.run(debug=True)