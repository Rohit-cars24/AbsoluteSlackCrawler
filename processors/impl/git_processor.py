from datetime import datetime, timezone
from flask import jsonify
from slack_sdk import WebClient
from google import genai
from google.genai import types

from processors.base_processor import BaseProcessor
from config.config import get_config
from config.database import get_mongo_client

class GitProcessor(BaseProcessor):
    """Processor for git-related messages"""
    
    def __init__(self):
        super().__init__()
        config = get_config()
        
        # Set up MongoDB collections
        mongo_client = get_mongo_client()
        db = mongo_client["hrbp"]
        self.collection = db["GitRequests"]
        self.collection_user = db["profiles"]
        
        # Set up Slack client
        self.slack_client = WebClient(config["SLACK_BOT_TOKEN"])
        self.channel_id = config["GIT_CHANNEL_ID"]
        
        # Set up Gemini client
        self.ai_client = genai.Client(api_key=config["GEMINI_API_KEY"])
    
    def classify_message(self, message, user_id):
        """Classify git messages using Gemini API"""
        prompt = f"""
        You are an AI assistant analyzing Slack messages related to Git requests.

        **Your task:**
        1. **Classify the message into one of the following categories:**
        - **"Pull Request"** if the message is about a pull request.
        - **"Code Review"** if the message is asking for a code review.
        - **"Merge Request"** if the message is about merging code.
        - **"Branch Creation"** if the message is about creating a new branch.
        - **"Access Request"** if the message is requesting access to a repository.
        - **"Useless"** if the message does not indicate any Git-related request.

        2. **Extract relevant details:**
        - Extract the **repository name** if mentioned.
        - Extract the **branch name** if mentioned.
        - Extract the **PR number** if mentioned.
        - Extract the **purpose** or **description** if explicitly mentioned.

        **User ID:** {user_id}
        **Message:** "{message}"
        
        **Output Format (JSON):**
        {{
        "request_type": "Classification",
        "repository": "Repository Name (if any)",
        "branch": "Branch Name (if any)",
        "pr_number": "PR Number (if any)",
        "purpose": "Purpose/Description (if any)"
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
                config=generate_content_config,
            )

            if response and response.text:
                import json
                try:
                    return json.loads(response.text.strip())
                except json.JSONDecodeError as e:
                    print(f"Error decoding JSON: {e}, response: {response.text}")
                    return {"request_type": "Useless", "repository": "", "branch": "", "pr_number": "", "purpose": ""}

        except Exception as e:
            print(f"Error calling Gemini API: {e}")

        return {"request_type": "Useless", "repository": "", "branch": "", "pr_number": "", "purpose": ""}
        
    def handle_new_message(self, event):
        """Process a new message"""
        message = event.get("text", "")
        user_id = event.get("user", "")
        message_id = event.get("ts", "")
        message_timestamp = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        
        print(f"New git message detected: {message} (Message ID: {message_id})")
        
        git_data = self.classify_message(message, user_id)
        request_type = git_data.get("request_type", "Useless")
        
        if request_type != "Useless":
            user_email = self.get_user_email(user_id)
            username = self.get_username(user_id)
            
            git_request = {
                'userid': user_id,
                'username': username,
                'type': request_type,
                'repository': git_data.get("repository", ""),
                'branch': git_data.get("branch", ""),
                'pr_number': git_data.get("pr_number", ""),
                'purpose': git_data.get("purpose", ""),
                'messageid': message_id,
                'useremail': user_email,
                'created_at': message_timestamp,
                'message': message,
                'created_by': user_id,
            }
            
            try:
                result = self.collection.insert_one(git_request)
                print(f"Stored Git request in MongoDB: {result.inserted_id}")
            except Exception as e:
                print(f"Database insertion failed: {e}")
        
        return jsonify({"status": "success"}), 200
    
    def handle_message_changed(self, event):
        """Process an edited message"""
        message = event["message"].get("text", "")
        user_id = event["message"].get("user", "")
        message_id = event["message"].get("ts", "")
        
        print(f"Edited git message detected: {message} (Message ID: {message_id})")
        
        self.delete_from_db(message_id)
        
        # Process the edited message as a new message
        event["text"] = message
        event["user"] = user_id
        event["ts"] = message_id
        
        self.handle_new_message(event)
    
    def handle_message_deleted(self, event):
        """Process a deleted message"""
        message_id = event.get("deleted_ts", "")
        
        print(f"Deleted git message detected (Message ID: {message_id})")
        
        self.delete_from_db(message_id)
        return jsonify({"status": "success", "message": "Deleted from DB"}), 200
    
    def handle_channel_join(self, event):
        """Process a user joining channel"""
        user_id = event.get("user")
        print(f"New user joined git channel: {user_id}")
        
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
    
    def initialize_database(self):
        """Initialize database if needed"""
        # Check if GitRequests collection exists, create if not
        pass
    
    def sync_data(self):
        """Sync data with external sources if needed"""
        # For Git processor, might sync with GitHub/GitLab API
        pass