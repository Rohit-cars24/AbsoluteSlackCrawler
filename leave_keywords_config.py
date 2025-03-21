"""
Configuration file for leave message classification keywords and patterns
"""

# Keyword dictionaries for message classification
KEYWORD_PATTERNS = {
    "WFH": [
        r'\bwfh\b',
        r'\bwork(?:ing)? from home\b',
        r'\bremote(?:ly)?\b',
        r'\bhome office\b'
    ],
    "Unplanned Leave": [
        r'\bemergency leave\b',
        r'\bunexpected leave\b',
        r'\bunplanned leave\b',
        r'\bsudden leave\b'
    ],
    "Sick Leave": [
        r'\bsick leave\b',
        r'\bill(?:ness)?\b',
        r'\bfever\b',
        r'\bnot well\b',
        r'\bundertaking medications\b',
        r'\bmedical\b',
        r'\bhealth issues?\b',
        r'\bsick\b',
        r'\bdoctor\b',
        r'\bhospital\b'
    ],
    "Travelling": [
        r'\btravel(?:ling|ing)? to gurgaon\b',
        r'\bvisit(?:ing)? (?:the )?office\b',
        r'\bcoming to (?:the )?office\b',
        r'\bin office\b',
        r'\bin gurgaon\b'
    ],
    "Planned Leave": [
        r'\bplanned leave\b',
        r'\btaking (?:a )?leave\b',
        r'\bon leave\b',
        r'\bwill be (?:on|away)\b',
        r'\bvacation\b',
        r'\bholiday\b',
        r'\btime off\b',
        r'\bpersonal leave\b',
        r'\bwill not be available\b'
    ],
    "Leave Cancellation": [
        r'\bcancel(?:ing|led)? (?:my )?leave\b',
        r'\bwill be (?:coming|available)\b',
        r'\bno longer (?:on|taking) leave\b',
        r'\bback from leave\b',
        r'\breturning\b'
    ]
}

# Date pattern for extraction
DATE_PATTERNS = [
    # Today/tomorrow patterns
    r'(?:today|tomorrow|tmrw)',
    # DD/MM, DD-MM, DD.MM format
    r'\b(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](?:20)?\d{2})?\b',
    # DD Month, Month DD format
    r'\b(\d{1,2})(?:st|nd|rd|th)? (jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b',
    r'\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?) (\d{1,2})(?:st|nd|rd|th)?\b',
    # Next week/month patterns
    r'next (mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?|week|month)',
    # Range patterns
    r'from .*? to .*?',
    r'between .*? and .*?'
]