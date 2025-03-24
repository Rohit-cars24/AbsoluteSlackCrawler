"""
Configuration file for leave message classification keywords and patterns
"""

# Keyword dictionaries for message classification
KEYWORD_PATTERNS = {
    "WFH": [
        r'\bwfh\b',
        r'\bwork(?:ing)? from home\b',
        r'\bremote(?:ly)?\b',
        r'\bhome office\b',
    ],
    "Unplanned Leave": [
        r'\bemergency leave\b',
        r'\bunexpected leave\b',
        r'\bunplanned leave\b',
        r'\bsudden leave\b',
        r'\bnot coming (?:to office|to work)\b',
        r'\bnot be coming (?:to office|to work)\b',
        r'\btaking off\b',
        r'\booo\b',
        r'\bout of office\b',
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
    ],
    "Travelling": [
        r'\btravel(?:ling|ing)? to gurgaon\b',
        r'\bin gurgaon\b',
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
        r'\bwill not be available\b',
        r'\bwont be (available|coming)\b',
        r'\bnot available\b',
    ],
    "Leave Cancellation": [
        r'\bcancel(?:ing|led|ling)? (?:my )?leave\b',
        r'\bwill be (?:coming|available)\b',
        r'\bno longer (?:on|taking) leave\b',
        r'\bback from leave\b',
        r'\breturning\b',
        r'\bwill come to (?:office|work)\b',
    ]
}
