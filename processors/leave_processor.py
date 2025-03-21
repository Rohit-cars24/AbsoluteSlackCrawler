from datetime import datetime, timezone
from flask import jsonify
import requests
import re
from slack_sdk import WebClient
from google import genai
from google.genai import types

from processors.base_processor import BaseProcessor
from config import get_config
from database import get_mongo_client
# Import the keyword patterns from the config file
from leave_keywords_config import KEYWORD_PATTERNS, DATE_PATTERNS

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

        # Import keyword patterns from config
        self.keyword_patterns = KEYWORD_PATTERNS
        self.date_patterns = DATE_PATTERNS

    def classify_message_by_keywords(self, message):
        """Classify message based on keywords"""
        message_lower = message.lower()

        # Check each category's patterns
        for category, patterns in self.keyword_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    # Extract dates if a category is found
                    dates = self.extract_dates(message)
                    # Extract reason (simple implementation - everything after "reason" or "because")
                    reason_match = re.search(r'(?:reason|because|due to|as)\s*:?\s*(.*)', message_lower)
                    reason = reason_match.group(1).strip() if reason_match else ""

                    return {
                        "request_type": category,
                        "dates": dates,
                        "reason": reason
                    }

        # If no category matches
        return None

    def extract_dates(self, message):
        """Extract dates from a message"""
        message_lower = message.lower()
        today = datetime.now()
        dates = []

        # Handle today/tomorrow
        if "today" in message_lower:
            dates.append(today.strftime("%Y-%m-%d"))
        if any(word in message_lower for word in ["tomorrow", "tmrw"]):
            tomorrow = today.replace(day=today.day + 1)
            dates.append(tomorrow.strftime("%Y-%m-%d"))

        # Handle simple date formats (this is a basic implementation)
        # For a more robust solution, you would want to use a dedicated date parsing library

        # Example: Detect DD/MM/YYYY or DD/MM
        date_matches = re.finditer(r'\b(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](?:20)?(\d{2}))?\b', message_lower)
        for match in date_matches:
            day, month = int(match.group(1)), int(match.group(2))
            year = int(match.group(3)) if match.group(3) else today.year
            if year < 100:  # Handle two-digit years
                year += 2000
            try:
                # Validate date
                if 1 <= day <= 31 and 1 <= month <= 12:
                    date_str = f"{year}-{month:02d}-{day:02d}"
                    if date_str not in dates:
                        dates.append(date_str)
            except ValueError:
                # Invalid date, skip
                pass

        # For a production system, consider using a library like dateparser
        # This would handle many more date formats and linguistic patterns

        return dates

    def classify_message(self, message, user_id):
        """Classify leave messages using keywords first, fall back to Gemini API"""
        # First try keyword classification
        keyword_result = self.classify_message_by_keywords(message)

        if keyword_result and keyword_result["request_type"] != "Useless" and keyword_result["dates"]:
            print(f"Message classified by keywords as {keyword_result['request_type']}")
            return keyword_result

        # Fall back to Gemini API for more complex messages
        print("Keyword classification failed or insufficient. Using Gemini API...")
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

    # The rest of the methods remain the same as in the previous version
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

        if self.message_exists(message_id) and (current_time - message_time).total_seconds() > 7200:  # 2 hours
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

        print("Database is now in sync with Slack channel!")