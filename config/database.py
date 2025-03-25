import pymongo
from config.config import get_config

# Global MongoDB client to be reused
_mongo_client = None

def get_mongo_client():
    """
    Get MongoDB client connection (singleton pattern)
    
    Returns:
        pymongo.MongoClient: MongoDB client
    """
    global _mongo_client
    
    if _mongo_client is None:
        config = get_config()
        mongo_uri = config["MONGO_URI"]
        
        if not mongo_uri:
            raise ValueError("MongoDB URI not configured. Set MONGO_URI in environment.")
        
        try:
            _mongo_client = pymongo.MongoClient(mongo_uri)
            # Test the connection
            _mongo_client.admin.command('ping')
            print("MongoDB connection established successfully")
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise
    
    return _mongo_client