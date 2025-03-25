from processors.impl.leave_processor import LeaveProcessor
from processors.impl.git_processor import GitProcessor
# from processors.jira_processor import JiraProcessor

class ChannelProcessorFactory:
    """
    Factory class that creates different processors based on channel type
    """
    
    def __init__(self):
        self.processors = {}
        self._register_processors()
    
    def _register_processors(self):
        """Register all available processors"""
        self.processors["leave"] = LeaveProcessor()
        self.processors["git"] = GitProcessor()
        # self.processors["jira"] = JiraProcessor()
        # Add more processors as needed
    
    def get_processor(self, channel_type):
        """
        Get appropriate processor based on channel type
        
        Args:
            channel_type (str): Type of channel ("leave", "git", "jira", etc.)
            
        Returns:
            BaseProcessor: Appropriate processor for the channel type
        """
        return self.processors.get(channel_type)