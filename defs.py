from dotenv import load_dotenv
load_dotenv()

DB_INIT_SQL = """
CREATE TABLE IF NOT EXISTS logs (
    id integer PRIMARY KEY,
    event text NOT NULL,
    trigger text NOT NULL,
    message_id integer,
    handled_by text,
    state text NOT NULL,
    result text,
    created_on time(s)tamp NOT NULL
)
"""


class MQTTTOPIC:
    BELL_ONLINE = 'sherangthebell/status'
    RANG_THE_BELL = 'sherangthebell/bell'
    TAKE_HER_OUT = 'sherangthebell/take'


class EVENT:
    RING = 'ring'


class TRIGGER:
    MANUAL = 'manual'
    TARLY = 'tarly'


class CALLBACK:
    TAKE_HER_OUT = 'take_her_out'
    RECORD_SURVEY = 'record_survey'
    DISMISS = 'dismiss'


class STATE:
    INITIATED = 'INITIATED'
    CLAIMED = 'CLAIMED'
    SURVEYED = 'SURVEYED'
    COMPLETED = 'COMPLETED'
    DISMISSED = 'DISMISSED'


class RESULT:
    NUMBER_1 = '1'
    NUMBER_2 = '2'
    BOTH = 'BOTH'
    NOTHING = 'NOTHING'