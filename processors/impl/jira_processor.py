from datetime import datetime, timezone
from flask import jsonify
from slack_sdk import WebClient
from google import genai
from google.genai import types

from processors.base_processor import BaseProcessor
from config.config import get_config
from config.database import get_mongo_client

class JiraProcessor(BaseProcessor):
    """Processor for jira-related messages"""
    
    def __init__(self):
        super().__init__()
        config = get_config()
        
        # Set up MongoDB collections
        mongo_client = get_mongo_client()
        db = mongo_client["hrbp"]
        self.collection = db["JiraRequests"]
        self.collection_user = db["profiles"]
        
        # Set up Slack client
        self.slack_client = WebClient(config["SLACK_BOT_TOKEN"])
        self.channel_id = config["JIRA_CHANNEL_ID"]
        
        # Set up Gemini client
        self.ai_client = genai.Client(api_key=config["GEMINI_API_KEY"])
    
    def classify_message(self, message, user_id):
        """Classify jira messages using Gemini API"""
        prompt = f"""
        You are an AI assistant analyzing Slack messages related to Jira tickets and requests.

        **Your task:**
        1. **Classify the message into one of the following categories:**
        - **"Bug Report"** if the message is reporting a bug or issue.
        - **"Feature Request"** if the message is requesting a new feature.
        - **"Task Assignment"** if the message is about assigning a task.
        - **"Status Update"** if the message is providing an update on a ticket.
        - **"Ticket Creation"** if the message is about creating a new ticket.
        - **"Access Request"** if the message is requesting access to Jira.
        - **"Useless"** if the message does not indicate any Jira-related request.

        2. **Extract relevant details:**
        - Extract the **ticket ID** if mentioned (e.g., PROJ-123).
        - Extract the **project key** if mentioned (e.g., PROJ).
        - Extract the **priority** if mentioned.
        - Extract the **description** of the issue or request.
        - Extract **assignee** if mentioned.

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
        
        return {
            "request_type": "Useless", 
            "ticket_id": "", 
            "project_key": "", 
            "priority": "", 
            "description": "",
            "assignee": ""
        }
    
    def handle_new_message(self, event):
        """Process a new message"""
        message = event.get("text", "")
        user_id = event.get("user", "")
        message_id = event.get("ts", "")
        message_timestamp = datetime.fromtimestamp(float(message_id), tz=timezone.utc)
        
        print(f"New Jira message detected: {message} (Message ID: {message_id})")
        
        jira_data = self.classify_message(message, user_id)
        request_type = jira_data.get("request_type", "Useless")
        
        if request_type != "Useless":
            user_email = self.get_user_email(user_id)
            username = self.get_username(user_id)
            
            jira_request = {
                'userid': user_id,
                'username': username,
                'type': request_type,
                'ticket_id': jira_data.get("ticket_id", ""),
                'project_key': jira_data.get("project_key", ""),
                'priority': jira_data.get("priority", ""),
                'description': jira_data.get("description", ""),
                'assignee': jira_data.get("assignee", ""),
                'messageid': message_id,
                'useremail': user_email,
                'created_at': message_timestamp,
                'message': message,
                'created_by': user_id,
            }
            
            try:
                result = self.collection.insert_one(jira_request)
                print(f"Stored Jira request in MongoDB: {result.inserted_id}")
                
                # If this is a bug report or feature request, we might want to 
                # automatically create a Jira ticket via API (not implemented here)
                if request_type in ["Bug Report", "Feature Request"]:
                    print(f"TODO: Create actual Jira ticket for {request_type}")
                    # self.create_jira_ticket(jira_request)
                
            except Exception as e:
                print(f"Database insertion failed: {e}")
        
        return jsonify({"status": "success"}), 200
    
    def handle_message_changed(self, event):
        """Process an edited message"""
        message = event["message"].get("text", "")
        user_id = event["message"].get("user", "")
        message_id = event["message"].get("ts", "")
        
        print(f"Edited Jira message detected: {message} (Message ID: {message_id})")
        
        self.delete_from_db(message_id)
        
        # Process the edited message as a new message
        event["text"] = message
        event["user"] = user_id
        event["ts"] = message_id
        
        self.handle_new_message(event)
    
    def handle_message_deleted(self, event):
        """Process a deleted message"""
        message_id = event.get("deleted_ts", "")
        
        print(f"Deleted Jira message detected (Message ID: {message_id})")
        
        # For Jira tickets, we may want to keep a record that it was deleted
        # rather than actually deleting it from the database
        jira_entry = self.collection.find_one({"messageid": message_id})
        
        if jira_entry and jira_entry.get("ticket_id"):
            # If there's an actual Jira ticket associated, mark as deleted but don't remove
            self.collection.update_one(
                {"messageid": message_id},
                {"$set": {"deleted": True, "deleted_at": datetime.now(timezone.utc)}}
            )
            print(f"Marked Jira ticket as deleted: {message_id}")
        else:
            # Otherwise just delete it
            self.delete_from_db(message_id)
        
        return jsonify({"status": "success", "message": "Processed deletion"}), 200
    
    def handle_channel_join(self, event):
        """Process a user joining channel"""
        user_id = event.get("user")
        print(f"New user joined Jira channel: {user_id}")
        
        if not self.collection_user.find_one({"slackid": user_id}):
            user_info = self.fetch_user_profile(user_id)
            if user_info:
                self.collection_user.insert_one(user_info)
                print(f"User {user_id} added to the database.")
                
                # Welcome the user
                welcome_message = (
                    f"Welcome to the Jira channel <@{user_id}>! "
                    "You can post bug reports, feature requests, and ticket updates here. "
                    "Our bot will analyze your messages and create appropriate tickets."
                )
                self.slack_client.chat_postEphemeral(
                    channel=self.channel_id,
                    user=user_id,
                    text=welcome_message
                )
            else:
                print(f"Failed to fetch details for {user_id}")
    
    def delete_from_db(self, message_id):
        """Delete records from database by message ID"""
        if message_id:
            self.collection.delete_many({"messageid": message_id})
            print(f"Deleted from MongoDB: {message_id}")
    
    def initialize_database(self):
        """Initialize database if needed"""
        # Ensure indexes exist for faster queries
        if self.collection:
            self.collection.create_index("messageid")
            self.collection.create_index("ticket_id")
            self.collection.create_index("userid")
            print("Jira collection indexes created")
    
    def sync_data(self):
        """Sync data with Jira if needed"""
        # This would connect to Jira API and sync ticket statuses
        # Not implemented in this example
        print("Jira data sync would happen here")
        
    # Additional methods that could be implemented
    
    def create_jira_ticket(self, jira_request):
        """Create an actual Jira ticket via API"""
        # This would use the Jira API to create a ticket
        # Not implemented in this example
        pass
    
    def update_jira_ticket(self, ticket_id, update_data):
        """Update a Jira ticket via API"""
        # This would use the Jira API to update a ticket
        # Not implemented in this example
        pass
    
    def fetch_jira_ticket_status(self, ticket_id):
        """Fetch the current status of a Jira ticket"""
        # This would use the Jira API to get ticket status
        # Not implemented in this example
        pass