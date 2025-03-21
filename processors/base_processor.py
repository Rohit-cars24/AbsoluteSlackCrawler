from abc import ABC, abstractmethod
from datetime import datetime, timezone

class BaseProcessor(ABC):
    """
    Abstract base class for all channel processors
    """
    
    def __init__(self):
        """Initialize processor with common attributes"""
        self.collection = None
        self.collection_user = None
        self.slack_client = None
        self.ai_client = None
    
    def process_event(self, event):
        """
        Process a Slack event based on its type
        
        Args:
            event (dict): Slack event data
        """
        if event.get("subtype") == "message_changed":
            self.handle_message_changed(event)
        elif event.get("subtype") == "message_deleted":
            self.handle_message_deleted(event)
        elif event.get("subtype") == "channel_join":
            self.handle_channel_join(event)
        else:
            self.handle_new_message(event)
    
    @abstractmethod
    def classify_message(self, message, user_id):
        """
        Classify the message using AI
        
        Args:
            message (str): Message text
            user_id (str): User ID
            
        Returns:
            dict: Classification results
        """
        pass
    
    @abstractmethod
    def handle_new_message(self, event):
        """Process a new message"""
        pass
    
    @abstractmethod
    def handle_message_changed(self, event):
        """Process an edited message"""
        pass
    
    @abstractmethod
    def handle_message_deleted(self, event):
        """Process a deleted message"""
        pass
    
    @abstractmethod
    def handle_channel_join(self, event):
        """Process a user joining channel"""
        pass
    
    @abstractmethod
    def initialize_database(self):
        """Initialize database collections"""
        pass
    
    @abstractmethod
    def sync_data(self):
        """Sync data with external sources"""
        pass
    
    def get_user_email(self, user_id):
        """Get user email from Slack"""
        if not user_id:
            return None
        
        try:
            user_info = self.slack_client.users_info(user=user_id)
            if user_info.get("ok"):
                return user_info["user"]["profile"]["email"]
        except Exception as e:
            print(f"Error fetching user email for {user_id}: {e}")
        
        return None
    
    def get_username(self, user_id):
        """Get username from Slack"""
        if not user_id:
            return "Unknown User"
        
        try:
            response = self.slack_client.users_info(user=user_id)
            if response.get("ok"):
                return response["user"]["profile"].get("real_name", 
                                                      response["user"]["profile"].get("name", "Unknown User"))
        except Exception as e:
            print(f"Error fetching username for {user_id}: {e}")
        
        return "Unknown User"
    
    def fetch_user_profile(self, user_id):
        """Fetch user profile from Slack"""
        if not user_id:
            return None
        
        try:
            response = self.slack_client.users_info(user=user_id)
            if response.get("ok"):
                user = response["user"]
                return {
                    "slackid": user["id"],
                    "name": user["profile"].get("real_name", ""),
                    "email": user["profile"].get("email", ""),
                    "phone": user["profile"].get("phone", "")
                }
        except Exception as e:
            print(f"Error fetching user profile for {user_id}: {e}")
        
        return None