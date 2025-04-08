

from datetime import datetime, timezone
from flask import jsonify
import requests
import re
from slack_sdk import WebClient
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from processors.base_processor import BaseProcessor
from config.config import get_config
from config.database import get_mongo_client

class LeaveProcessor(BaseProcessor):
    """Processor for leave-related messages"""
    
    def __init__(self):
        super().__init__()
        config = get_config()
        
        # Set up MongoDB collections
        mongo_client = get_mongo_client()
        self.db = mongo_client["hrbp"]
        self.collection = self.db["Attendance"]
        self.collection_user = self.db["profiles"]
        
        self.audit_collection = self.db["AttendanceAudit"] 

        # Set up Slack client
        self.slack_client = WebClient(config["SLACK_BOT_TOKEN"])
        self.channel_id = config["LEAVE_CHANNEL_ID"]
        
        # Set up Gemini client
        self.ai_client = genai.Client(api_key=config["GEMINI_API_KEY"])
    

    def load_keyword_patterns(self):
        """Fetch keyword patterns from MongoDB."""
        keyword_patterns = {}
        for entry in self.db.keyword_patterns.find({}, {"_id": 0, "category": 1, "patterns": 1}):
            keyword_patterns[entry["category"]] = entry["patterns"]

        return keyword_patterns
        
    
    def classify_message_by_keywords(self, message):
        """Classify message based on keywords"""
        message_lower = message.lower()

        keywords_patterns = self.load_keyword_patterns()
        print(f"Keywords patterns loaded: {keywords_patterns}")
        
        # Check each category's patterns
        for category, patterns in keywords_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message_lower):
                    dates = self.extract_dates(message)

                    print(category, dates)
                    
                    return {
                        "request_type": category,
                        "dates": dates,
                    }
        
        return None
    
    def extract_dates(self, message):
        message_lower = message.lower()
        today = datetime.now()
        dates = []

        # Today/tomorrow/tomo/tmrw
        if any(word in message_lower for word in ["today", "tomorrow", "tmrw", "tomo", "tdy"]):
            if any(word in message_lower for word in ["today", "tdy"]):
                dates.append(today.strftime("%Y-%m-%d"))
            if any(word in message_lower for word in ["tomorrow", "tmrw", "tomo"]):
                tomorrow = today + timedelta(days=1)
                dates.append(tomorrow.strftime("%Y-%m-%d"))

        if re.search(r'\bnext(\s+(week|month))?\b', message.lower()):
            return dates  # Skip next week/month for now

        # DD/MM, DD-MM, DD.MM format
        match_iter = re.finditer(r'\b(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?\b', message)
        for match in match_iter:
            if not match:
                continue
            day, month = match.group(1), match.group(2)
            if not day or not month:
                continue
            day, month = int(day), int(month)
            year = int(match.group(3)) if match.group(3) else today.year
            if match.group(3) and len(match.group(3)) == 2:
                year += 2000
            try:
                date_obj = datetime(year, month, day)
                dates.append(date_obj.strftime("%Y-%m-%d"))
            except ValueError:
                pass 

        # DD Month format
        match_iter = re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+'
            r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)'
            r'(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?\b',
            message_lower, re.IGNORECASE)

        month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

        for match in match_iter:
            day = int(match.group(1))
            month_str = match.group(2)[:3].lower()
            month = month_map.get(month_str)
            
            if month:
                try:
                    date_obj = datetime(today.year, month, day)
                    dates.append(date_obj.strftime("%Y-%m-%d"))
                except ValueError:
                    pass

        # Month DD format
        match_iter = re.finditer(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)'
                             r'(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?\s+'
                             r'(\d{1,2})(?:st|nd|rd|th)?\b', message, re.IGNORECASE)
    
        month_map = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                    'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}

        for match in match_iter:
            month_str = match.group(1)[:3].lower()  # Get first 3 letters of month
            day = int(match.group(2))  # Extract day
            month = month_map.get(month_str)

            if month:
                try:
                    date_obj = datetime(today.year, month, day)
                    dates.append(date_obj.strftime("%Y-%m-%d"))
                except ValueError:
                    pass  # Ignore invalid dates (e.g., Feb 30)

        # This week
        match = re.search(r'\b(mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', message.lower())

        day_map = {
            'mon': 0, 'monday': 0, 
            'tue': 1, 'tuesday': 1, 
            'wed': 2, 'wednesday': 2, 
            'thu': 3, 'thursday': 3, 
            'fri': 4, 'friday': 4, 
            'sat': 5, 'saturday': 5, 
            'sun': 6, 'sunday': 6
        }

        if match:
            target_day = day_map[match.group(1)]
            days_ahead = (target_day - today.weekday() + 7) % 7
            if days_ahead == 0:  # If today is the same day, move to next week's occurrence
                days_ahead = 7

            next_day = today + timedelta(days=days_ahead)
            dates.append(next_day.strftime("%Y-%m-%d"))

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

            **For the below input Assume today's date is 2025-04-08(yyyy-mm-dd). But when returning the messages, dates shld be with refernce to the currrent date you get the message But make user that today and tomorrow requests if they come, take today's actual date and give me accordingly for dates. Please dont use the same dates that i have mentioned, check the present date and give today or tomorrow according to the present date**

            ---
            **Example Inputs & Outputs:**
            
            - **Message:** "I will be coming to office today."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-04-08"], "reason": ""}}

            - **Message:** "I had applied for leave, but now I will come tomorrow."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-04-09"], "reason": ""}}

            - **Message:** "I won't be on leave next Wednesday."
            **Output:** {{"request_type": "Leave Cancellation", "dates": ["2025-04-09"], "reason": ""}}

            - **Message:** "Hey, I will be working from home today due to personal reasons."
            **Output:** {{"request_type": "WFH", "dates": ["2025-04-08"], "reason": "personal reasons"}}

            - **Message:** "I am not coming to office tomorrow."
            **Output:** {{"request_type": "Planned Leave", "dates": ["2025-04-09"], "reason": "personal reasons"}}

            - **Message:** "will be unavailable from 2:00 to 5:00 since need to take my daughter for vaccination and doctor checkup"
            **Output:** {{"request_type": "Useless", "dates": [], "reason": ""}}

            - **Message:** "I will not be coming to office on monday and tuesday as mentioned earlier."
            **Output:** {{"request_type": "Planned Leave", "dates": ["2025-04-14", "2025-04-15"], "reason": "personal reasons"}}

            - **Message:** "I need unplanned leave today because of an emergency."
            **Output:** {{"request_type": "Unplanned Leave", "dates": ["2025-04-08"], "reason": "emergency"}}

            - **Message:** "I am traveling to Gurgaon for an event tomorrow."
            **Output:** {{"request_type": "Travelling", "dates": ["2025-04-09"], "reason": "event"}}

            - **Message:** "Good morning team!"
            **Output:** {{"request_type": "Useless", "dates": [], "reason": ""}}

        ---
        
        **User ID:** {user_id}  
        **Message:** "{message}"

        **Output Format (JSON):**
        {{
          "request_type": "Classification",
          "dates": ["YYYY-MM-DD", ...],
          "reason": "Reason for the request (if any)"
        }}
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
                import json
                try:
                    return json.loads(response.text.strip())
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}, response: {response.text}")
                    return {"request_type": "Useless", "dates": [], "reason": ""}
            
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
        
        return {"request_type": "Useless", "dates": [], "reason": ""}
    
    # The rest of the methods remain the same as in the previous version
    def handle_new_message(self, event):
        """Process a new message"""
        self.handle_audit_for_message(event, "NEW")
        message = event.get("text", "")
        user_id = event.get("user", "")
        message_id = event.get("ts", "")
        message_timestamp = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        
        print(f"New leave message detected: {message} (Message ID: {message_id})")
        
        leave_data = self.classify_message(message, user_id)
        request_type = leave_data.get("request_type", "Useless")
        dates = leave_data.get("dates", [])
        
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

                self.remove_request_db(user_id, leave_date)
                
                try:
                    result = self.collection.insert_one(leave_request)
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
        user_id = event.get("previous_message", {}).get("user", "")

        channel_id = event.get("channel")
        
        print(f"Deleted leave message detected (Message ID: {message_id})")
        
        message_time = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        current_time = datetime.now(timezone.utc)

        print(f"Current time: {current_time}, Message time: {message_time}")
        
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
                channel=channel_id,
                user=user_id,
                text=delete_message
            )
            
            return jsonify({
                "status": "failed",
                "message": "Deletion failed: Time exceeded 2 hours. Your leave request is already submitted, contact your HR."
            }), 400
        
        self.delete_from_db(message_id)
        self.handle_audit_for_message(event,"DELETE")

        return jsonify({"status": "success", "message": "Deleted from DB"}), 200
    
    def handle_channel_join(self, event):
        """Process a user joining channel"""
        user_id = event.get("user")
        print(f"New user joined leave channel: {user_id}")

        channel_id = event.get("channel")
        print('////////////////////////')
        print(f"Channel ID: {channel_id}")
        
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

