import pandas as pd
from datetime import datetime, timezone, date
from flask import jsonify
import requests
import re
from slack_sdk import WebClient
from google import genai
from datetime import datetime
from processors.base_processor import BaseProcessor
from config.config import get_config
from config.database import get_mongo_client
from slack_sdk.errors import SlackApiError
import os

class ReleaseLogProcessor(BaseProcessor):
    """Processor for leave-related messages"""
    
    def __init__(self):
        super().__init__()
        config = get_config()
        
        # Set up MongoDB collections
        mongo_client = get_mongo_client()
        self.db = mongo_client["hrbp"]
        self.collection = self.db["ReleaseLog"]
        self.collection_user = self.db["profiles"]
        
        self.audit_collection = self.db["ReleaseLogAudit"]

        # Set up Slack client
        self.slack_client = WebClient(config["SLACK_BOT_TOKEN"])
        
        # Set up Gemini client
        self.ai_client = genai.Client(api_key=config["GEMINI_API_KEY"])


    
    def fetch_data(self, from_date, to_date):
        """Fetch records from MongoDB within the given date range."""
        # Convert dates to string format as stored in MongoDB
        from_date_str = datetime.strptime(from_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        to_date_str = datetime.strptime(to_date, "%Y-%m-%d").strftime("%Y-%m-%d")

        query = {
            "date": {"$gte": from_date_str, "$lte": to_date_str}  # Compare as strings
        }
        records = self.collection.find(query, {"_id": 0, "date": 1, "username": 1, "message": 1})

        return list(records)

    def generate_excel_report(self, from_date, to_date, output_file="report.xlsx"):
        """Generate an Excel report from MongoDB data."""
        print(f"Generating report from {from_date} to {to_date}...")
        data = self.fetch_data(from_date, to_date)
        print(data)
        
        if not data:
            return None
        
        df = pd.DataFrame(data)
        df.to_excel(output_file, index=False, engine="openpyxl")
        
        return output_file

    def send_file_to_slack(self, file_path, channel_id):
        """Send a file to Slack channel."""
        try:
            if not os.path.exists(file_path):
                print("Error: File not found!")
                return
            
            response = self.slack_client.files_upload(
                channels=channel_id,
                file=file_path,
                title="Generated Report",
                initial_comment="Here is your requested report 📄"
            )
            print("File uploaded successfully!", response)
        
        except SlackApiError as e:
            print(f"Error uploading file: {e.response['error']}")


    def load_keyword_patterns(self):
        """Fetch keyword patterns from MongoDB."""
        keyword_patterns = {}
        for entry in self.db.keyword_patterns.find({}, {"_id": 0, "category": 1, "patterns": 1}):
            keyword_patterns[entry["category"]] = entry["patterns"]

        return keyword_patterns
    
    def process_message(self, text):
        match = re.search(r'Overview\s*:\s*(.*)', text, re.IGNORECASE)
        return match.group(1) if match else "No overview found"
    
    # The rest of the methods remain the same as in the previous version
    def handle_new_message(self, event):
        """Process a new message"""
        self.handle_audit_for_message(event, "NEW")
        message = event.get("text", "")
        user_id = event.get("user", "")
        message_id = event.get("ts", "")
        message_timestamp = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        
        print(f"New leave message detected: {message} (Message ID: {message_id})")
        
        releaselog_data = self.process_message(message)
        current_date = date.today().isoformat()
        
        user_email = self.get_user_email(user_id)
        username = self.get_username(user_id)
        
        releaselog_request = {
            'username': username,
            'date': current_date,
            'messageid': message_id,
            'useremail': user_email,
            'created_at': message_timestamp,
            'message': releaselog_data,
            'created_by': user_id,
        }
            
        try:
            result = self.collection.insert_one(releaselog_request)
            print(f"Stored in MongoDB: {result.inserted_id}")
        except Exception as e:
            print(f"Database insertion failed: {e}")
        
        return jsonify({"status": "success"}), 200
    
    def handle_message_changed(self, event):
        """Process an edited message"""
        self.handle_audit_for_message(event, "EDIT")
        message = event["message"].get("text", "")
        user_id = event["message"].get("user", "")
        message_id = event["message"].get("ts", "")
        
        print(f"Edited leave message detected: {message} (Message ID: {message_id})")
        
        self.delete_from_db(message_id)
        
        # Process the edited message as a new message
        event["text"] = message
        event["user"] = user_id
        event["ts"] = message_id
        
        self.handle_new_message(event)
    
    def handle_message_deleted(self, event):
        """Process a deleted message"""
        message_id = event.get("deleted_ts", "")        
        print(f"Deleted leave message detected (Message ID: {message_id})")
        
        self.delete_from_db(message_id)
        self.handle_audit_for_message(event,"DELETE")

        return jsonify({"status": "success", "message": "Deleted from DB"}), 200
    
    def handle_channel_join(self, event):
        """Process a user joining channel"""
        user_id = event.get("user")
        print(f"New user joined leave channel: {user_id}")
        
        if not self.collection_user.find_one({"slackid": user_id}):
            user_info = self.fetch_user_profile(user_id)
            if user_info:
                self.collection_user.insert_one(user_info)
                print(f"User {user_id} added to the database.")
            else:
                print(f"Failed to fetch details for {user_id}")

    def remove_request_db(self, user_id, date):
        """Remove leave requests from database"""
        result = self.collection.delete_many({"userid": user_id, "date": date})
        print(f"Deleted {result.deleted_count} leave request(s) for {user_id} on date: {date}")
    
    def delete_from_db(self, message_id):
        """Delete records from database by message ID"""
        if message_id:
            self.collection.delete_many({"messageid": message_id})
            print(f"Deleted from MongoDB: {message_id}")
    
    def update_db(self, user_id, dates):
        """Update database for leave cancellations"""
        query = {"userid": user_id, "date": {"$in": dates}}
        
        result = self.collection.delete_many(query)
        
        if result.deleted_count > 0:
            print(f"Deleted {result.deleted_count} leave(s) for {user_id} on dates: {dates}")
        else:
            print(f"No matching leave found for {user_id} on dates: {dates}")
        
        return result.deleted_count
    
    def message_exists(self, message_id):
        """Check if a message exists in the database"""
        return self.collection.find_one({"messageid": message_id}) is not None
    
    def fetch_all_members(self):
        """Fetch all users in the Slack channel"""
        url = "https://slack.com/api/users.list"
        headers = {"Authorization": f"Bearer {get_config()['SLACK_BOT_TOKEN']}"}
        response = requests.get(url, headers=headers).json()
        
        if response["ok"]:
            return response["members"]
        
        return []
    
    def initialize_database(self):
        """Initialize database if empty"""
        if self.collection_user.count_documents({}) == 0:
            print("Database is empty! Fetching all members from Slack...")
            all_members = self.fetch_all_members()
            
            for member in all_members:
                user_info = self.fetch_user_profile(member.get("id"))
                if user_info:
                    self.collection_user.insert_one(user_info)
            
            print("All members added to the database!")
    
    def sync_data(self):
        """Sync missing users with Slack"""
        all_members = self.fetch_all_members()
        
        existing_users = {user["slackid"] for user in self.collection_user.find({}, {"slackid": 1})}
        
        for member in all_members:
            user_id = member.get("id")
            if user_id not in existing_users:
                print(f"User {user_id} is missing in DB. Adding now...")
                user_info = self.fetch_user_profile(user_id)
                if user_info:
                    self.collection_user.insert_one(user_info)
        
        print("Database is now in sync with Slack channel!")


    def create_audit_entry(self, user_id, full_message, action, reference_id=None, message_id=None):
        """Creates an audit entry in AttendanceAudit collection"""
        user_info = self.fetch_user_profile(user_id)
        username = user_info.get("name", "Unknown")
        created_timestamp = datetime.now(timezone.utc)

        audit_entry = {
            "username": username,
            "userid": user_id,
            "Full message": full_message,
            "created timestamp": created_timestamp,
            "Action": action,
            "message_id": message_id  # Store Slack's message timestamp
        }

        # Add reference for EDIT/DELETE actions
        if action in ["EDIT", "DELETE"] and reference_id:
            audit_entry["reference"] = reference_id

        # Insert into AttendanceAudit collection
        result = self.audit_collection.insert_one(audit_entry)
        return result.inserted_id

    def handle_audit_for_message(self, event, action):
        """Handles audit entries for NEW, EDIT, or DELETE actions"""
        if action == "NEW":
            message = event.get("text", "")
            user_id = event.get("user", "")
            message_id = event.get("ts", "")
        elif action == "EDIT":
            message = event.get("message", {}).get("text", "")
            user_id = event.get("message", {}).get("user", "")
            message_id = event.get("message", {}).get("ts", "")
        elif action == "DELETE":
            message = event.get("previous_message", {}).get("text", "")
            user_id = event.get("previous_message", {}).get("user", "")
            message_id = event.get("previous_message", {}).get("ts", "")

        if not message or not user_id:
            print(f"Ignoring event: No message or user_id found for action {action}")
            return

        if action == "NEW":
            self.create_audit_entry(user_id, message, "NEW", message_id=message_id)
        else:
            # For EDIT/DELETE, find previous audit entry by message_id
            previous_audit = self.audit_collection.find_one(
                {"message_id": message_id},
                sort=[("created timestamp", -1)]
            )

            if previous_audit:
                self.create_audit_entry(
                    user_id, 
                    message, 
                    action, 
                    reference_id=previous_audit["_id"],
                    message_id=message_id
                )
            else:
                self.create_audit_entry(user_id, message, "NEW", message_id=message_id)

