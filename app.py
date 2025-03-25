from flask import Flask, request, jsonify
import threading
import logging
from datetime import datetime

from config.config import get_config
from core.factory import ChannelProcessorFactory

app = Flask(__name__)
config = get_config()

# Create a factory to generate the appropriate processor based on channel type
channel_factory = ChannelProcessorFactory()

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
    
    if "event" in data:
        event = data["event"]
        channel_id = event.get("channel", "")
        
        # Determine channel type based on channel ID
        channel_type = ""  # Default

        channel_map = {}

        
        # Map channel IDs to channel types
        if channel_id in config["LEAVE_CHANNEL_ID"]:
            channel_map[channel_id] = "leave"

        if channel_id in config["GIT_CHANNEL_ID"]:
            channel_map[channel_id] = "git"

        if channel_id in config["JIRA_CHANNEL_ID"]:
            channel_map[channel_id] = "jira"
        
        channel_type = channel_map.get(channel_id, "unknown")
        print(channel_type)

        threading.Thread(target=handle_event, args=(event, channel_type)).start()
        
    return jsonify({"status": "OK"}), 200

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("Starting Flask server...")
    
    for processor_type in ["leave", "git", "jira"]:
        processor = channel_factory.get_processor(processor_type)
        if processor:
            processor.initialize_database()
            processor.sync_data()
    
    app.run(debug=True)