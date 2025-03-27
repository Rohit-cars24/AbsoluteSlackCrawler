import os
import json
import logging
from datetime import datetime
import threading

from flask import Flask, request, jsonify
from slack_sdk import WebClient
from dotenv import load_dotenv
from pathlib import Path

# Import your custom modules
from config.config import get_config
from config.database import get_mongo_client
from core.factory import ChannelProcessorFactory
from processors.impl.release_log import ReleaseLogProcessor

# Load environment variables
env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
config = get_config()

# Initialize Slack client
slack_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))

# Create a factory to generate the appropriate processor based on channel type
channel_factory = ChannelProcessorFactory()

# Cache for user selections
user_selections = {}

def get_channel_type(db, channel_id):
    """
    Retrieve the channel type from the database
    """
    channel_map = {}
    channels = db.channel_ids.find({})
    
    for channel in channels:
        if channel_id in channel["channel_id"]:
            channel_map[channel_id] = channel["channel_name"].lower().replace("_channel", "")
    
    return channel_map.get(channel_id, "unknown")

def send_download_report_modal(user_id, trigger_id):
    """
    Send a modal for downloading reports
    """
    slack_client.chat_postMessage(
        channel="C08J82R2WUA",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Please select the date range for the report:*"}
            },
            {
                "type": "input",
                "block_id": "from_date",
                "element": {"type": "plain_text_input", "action_id": "from_date_input"},
                "label": {"type": "plain_text", "text": "From Date (YYYY-MM-DD)"}
            },
            {
                "type": "input",
                "block_id": "to_date",
                "element": {"type": "plain_text_input", "action_id": "to_date_input"},
                "label": {"type": "plain_text", "text": "To Date (YYYY-MM-DD)"}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Download Report"},
                        "value": "generate_report",
                        "action_id": "generate_report_button"
                    }
                ]
            }
        ]
    )


def handle_event(event, channel_type):
    """
    Handle events based on channel type
    """
    with app.app_context():
        processor = channel_factory.get_processor(channel_type)
        if not processor:
            logger.error(f"No processor found for channel type: {channel_type}")
            return
        
        processor.process_event(event)

@app.route("/slack/command", methods=["POST"])
def download_request():
    """
    Handle download request command
    """
    data = request.form
    user_id = data.get("user_id")
    channel_id = data.get("channel_id")
    trigger_id = data.get("trigger_id")

    user_selections[user_id] = {"channel_id": channel_id}
    logger.info(f"Download report request triggered by: {user_id}")

    send_download_report_modal(user_id, trigger_id)

    return "", 200

def send_download_report_modal(user_id, trigger_id):
    """
    Send a modal for downloading reports
    """
    slack_client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "download_report_modal",
            "title": {"type": "plain_text", "text": "Download Report"},
            "submit": {"type": "plain_text", "text": "Generate"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "from_date",
                    "element": {
                        "type": "datepicker",
                        "action_id": "select_from_date",
                        "placeholder": {"type": "plain_text", "text": "Select start date"}
                    },
                    "label": {"type": "plain_text", "text": "From Date"}
                },
                {
                    "type": "input",
                    "block_id": "to_date",
                    "element": {
                        "type": "datepicker",
                        "action_id": "select_to_date",
                        "placeholder": {"type": "plain_text", "text": "Select end date"}
                    },
                    "label": {"type": "plain_text", "text": "To Date"}
                },
                {
                    "type": "input",
                    "block_id": "report_type",
                    "element": {
                        "type": "static_select",
                        "action_id": "select_report_type",
                        "placeholder": {"type": "plain_text", "text": "Select report type"},
                        "options": [
                            {
                                "text": {"type": "plain_text", "text": "Release Log"},
                                "value": "release_log"
                            }
                        ]
                    },
                    "label": {"type": "plain_text", "text": "Report Type"}
                }
            ]
        }
    )

def process_download_request(user_id, trigger_id, channel_id):
    """
    Process download request in a separate thread
    """
    send_download_report_modal(user_id, trigger_id)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    """
    Handle Slack events
    """
    data = request.json
    
    if "challenge" in data:
        return jsonify({"challenge": data["challenge"]})
    
    mongo_client = get_mongo_client()
    db = mongo_client["hrbp"]
    
    if "event" in data:
        event = data["event"]
        channel_id = event.get("channel", "")
        logger.info(f"Channel ID: {channel_id}")
        
        channel = get_channel_type(db, channel_id)
        logger.info(f"Channel fetched: {channel}")

        threading.Thread(target=handle_event, args=(event, channel)).start()
        
    return jsonify({"status": "OK"}), 200

@app.route("/slack/interactions", methods=["POST"])
def handle_interactions():
    """
    Handle Slack interactions
    """
    try:
        data = request.form
        payload = json.loads(data["payload"])  

        user_id = payload["user"]["id"]

        if payload["type"] == "view_submission" and payload["view"]["callback_id"] == "download_report_modal":
            values = payload["view"]["state"]["values"]
            
            from_date = values["from_date"]["select_from_date"]["selected_date"]
            to_date = values["to_date"]["select_to_date"]["selected_date"]
            report_type = values["report_type"]["select_report_type"]["selected_option"]["value"]

            channel_id = user_selections[user_id]["channel_id"]
            
            # Generate report based on selected type
            report_generator = ReleaseLogProcessor()

            if report_generator:
                print(f"Generating report from {from_date} to {to_date}")
                report_file = report_generator.generate_excel_report(from_date, to_date)

                if report_file:
                    report_generator.send_file_to_slack(report_file, channel_id)
                    slack_client.chat_postMessage(
                        channel=channel_id, 
                        text=f"Report generated successfully for {report_type} from {from_date} to {to_date}! 📄"
                    )
                else:
                    slack_client.chat_postMessage(
                        channel=channel_id, 
                        text="No records found for the given date range."
                    )

            return jsonify({"response_action": "clear"})

        return jsonify({"response_type": "ephemeral"})
    
    except Exception as e:
        logger.error(f"Error in handle_interactions: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    logger.info("Starting Flask server...")

    mongo_client = get_mongo_client()
    db = mongo_client["hrbp"]
    
    # Initialize and sync processors
    for processor_type in ["leave", "git", "jira"]:
        processor = channel_factory.get_processor(processor_type)
        if processor:
            processor.initialize_database()
            processor.sync_data()
    
    app.run(debug=True)