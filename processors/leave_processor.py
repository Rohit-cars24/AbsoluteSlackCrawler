from datetime import datetime, timezone
from flask import jsonify
import requests
from slack_sdk import WebClient
from google import genai
from google.genai import types

from processors.base_processor import BaseProcessor
from config import get_config
from database import get_mongo_client

class LeaveProcessor(BaseProcessor):
    """Processor for leave-related messages"""
    
    def __init__(self):
        super().__init__()
        config = get_config()
        
        # Set up MongoDB collections
        mongo_client = get_mongo_client()
        db = mongo_client["hrbp"]
        self.collection = db["Attendance"]
        self.collection_user = db["profiles"]
        
        # Set up Slack client
        self.slack_client = WebClient(config["SLACK_BOT_TOKEN"])
        self.channel_id = config["LEAVE_CHANNEL_ID"]
        
        # Set up Gemini client
        self.ai_client = genai.Client(api_key=config["GEMINI_API_KEY"])
    
    def classify_message(self, message, user_id):
        """Classify leave messages using Gemini API"""
        prompt = f"""
            You are an AI assistant analyzing Slack messages related to leave and work status updates.

            **Your task:**
            1. **Classify the message into one of the following categories:**
            - **"WFH"** (Work From Home) if the message is about working remotely.
            - **"Unplanned Leave"** if the message is about taking a leave suddenly.
            - **"Sick Leave"** if the message is about taking a leave due to illness.
            - **"Travelling"** if the message is about traveling to Gurgaon.
            - **"Planned Leave"** if the message is about taking a planned leave.
            - **"Leave Cancellation"** if the user is canceling a leave.
            - **"Useless"** if the message does not indicate WFH, leave, travel, or cancellation.

            2. **Extract relevant details:**
            - If classified as **"Leave Cancellation"**, extract the cancellation **date(s)**.
            - If classified as **"WFH"**, **"Unplanned Leave"**, **"Sick Leave"**, **"Planned Leave"**, or **"Travelling"**, extract the **date(s)** mentioned.
            - Extract the **reason** for the request if explicitly mentioned.

            **Assume today's date is 2025-03-20.**

            ---
            **Example Inputs & Outputs:**
            
            - **Message:** "I will be coming to office today."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-03-21"], "reason": ""}}

            - **Message:** "I had applied for leave, but now I will come tomorrow."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-03-22"], "reason": ""}}

            - **Message:** "I won't be on leave next Wednesday."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-03-26"], "reason": ""}}

            - **Message:** "Hey, I will be working from home today due to personal reasons."
            **Output:** {{"request_type": "WFH", "dates": ["2025-03-20"], "reason": "personal reasons"}}

            - **Message:** "I am not coming to office tomorrow."
            **Output:** {{"request_type": "Planned Leave", "dates": ["2025-03-21"], "reason": "personal reasons"}}

            - **Message:** "I will not be coming to office on monday and tuesday as mentioned earlier."
            **Output:** {{"request_type": "Planned Leave", "dates": ["2025-03-24", ["2025-03-25"]], "reason": "personal reasons"}}

            - **Message:** "I need unplanned leave today because of an emergency."
            **Output:** {{"request_type": "Unplanned Leave", "dates": ["2025-03-20"], "reason": "emergency"}}

            - **Message:** "I am traveling to Gurgaon for an event tomorrow."
            **Output:** {{"request_type": "Travelling", "dates": ["2025-03-21"], "reason": "event"}}

            - **Message:** "I will be a available on next friday"
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-03-28"], "reason": "event"}}

            - **Message:** "Good morning team!"
            **Output:** {{"request_type": "Useless", "dates": [], "reason": ""}}

            ---
            
            **User ID:** {user_id}  
            **Message:** "{message}"
        """

        model = "gemini-2.0-flash"
        contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=prompt)],
            ),
        ]
        generate_content_config = types.GenerateContentConfig(
            temperature=0.7,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
            response_mime_type="application/json",
        )



        try:
            response = self.ai_client.models.generate_content(
                model=model, 
                contents=contents, 
                config=generate_content_config
            )
            
            if response and response.text:
                return eval(response.text.strip())
            
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
        
        return {"request_type": "Useless", "dates": [], "reason": ""}
    

    
    def handle_new_message(self, event):
        """Process a new message"""
        message = event.get("text", "")
        user_id = event.get("user", "")
        message_id = event.get("ts", "")
        message_timestamp = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        
        print(f"New leave message detected: {message} (Message ID: {message_id})")
        
        leave_data = self.classify_message(message, user_id)
        request_type = leave_data.get("request_type", "Useless")
        dates = leave_data.get("dates", [])
        reason = leave_data.get("reason", "")
        
        if request_type == "Leave Cancellation" and dates:
            print("Message classified as leave cancellation")
            self.update_db(user_id, dates)
            return jsonify({"status": "success", "message": "Updated DB for leave cancellation"}), 200
        
        user_email = self.get_user_email(user_id)
        username = self.get_username(user_id)
        
        if request_type != "Useless":
            for leave_date in dates:
                leave_request = {
                    'userid': user_id,
                    'username': username,
                    'type': request_type,
                    'date': leave_date,
                    'messageid': message_id,
                    'useremail': user_email,
                    'created_at': message_timestamp,
                    'message': message,
                    'created_by': user_id,
                }
                
                try:
                    result = self.collection.insert_one(leave_request)
                    print("Inserted : ", leave_request)
                    print(f"Stored in MongoDB: {result.inserted_id}")
                except Exception as e:
                    print(f"Database insertion failed: {e}")
        
        return jsonify({"status": "success"}), 200
    
    def handle_message_changed(self, event):
        """Process an edited message"""
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
        user_id = event.get("previous_message", {}).get("user", "")
        
        print(f"Deleted leave message detected (Message ID: {message_id})")
        
        message_time = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        current_time = datetime.now(timezone.utc)
        
        if self.message_exists(message_id) and (current_time - message_time).total_seconds() > 2:  # 2 hours
            print("Deletion failed: Time exceeded 2 hours.")
            
            leave_entries = list(self.collection.find({"messageid": message_id}))
            
            if leave_entries:
                leave_details = "\n".join([
                    f"- {entry['date']} ({entry['type']})" for entry in leave_entries
                ])
                delete_message = f"<@{user_id}>,Your leave request(s) have already been submitted:\n{leave_details}\nDeletion is not allowed after 2 hours. Contact HR."
            else:
                delete_message = f"<@{user_id}>,No leave request found for this message ID. Possible manual deletion."
            
            print(delete_message)
            
            self.slack_client.chat_postEphemeral(
                channel=self.channel_id,
                user=user_id,
                text=delete_message
            )
            
            return jsonify({
                "status": "failed",
                "message": "Deletion failed: Time exceeded 2 hours. Your leave request is already submitted, contact your HR."
            }), 400
        
        self.delete_from_db(message_id)
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
        
        print("Database is now in sync with Slack channel! Leave-HRBP")