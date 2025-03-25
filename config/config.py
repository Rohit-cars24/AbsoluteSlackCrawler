import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def get_config():
    """
    Get configuration from environment variables
    
    Returns:
        dict: Configuration dictionary
    """
    return {
        # Slack configuration
        "SLACK_BOT_TOKEN": os.getenv("SLACK_BOT_TOKEN"),
        
        # Channel IDs
        "LEAVE_CHANNEL_ID": os.getenv("LEAVE_CHANNEL_ID"),
        "GIT_CHANNEL_ID": os.getenv("GIT_CHANNEL_ID"),
        "JIRA_CHANNEL_ID": os.getenv("JIRA_CHANNEL_ID"),
        
        # Database configuration
        "MONGO_URI": os.getenv("MONGO_URI"),
        
        # AI API keys
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),
        
        # Application settings
        "DEBUG": os.getenv("DEBUG", "False").lower() == "true",
        "PORT": int(os.getenv("PORT", "5000")),
        "HOST": os.getenv("HOST", "0.0.0.0"),
    }