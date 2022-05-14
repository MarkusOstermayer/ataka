import logging

from ataka.common.database.models import FlagStatus

import json
import requests


"""
import enum
class FlagStatus(str, enum.Enum):
    UNKNOWN = 'unknown'

    # everything is fine
    OK = 'ok'

    # Flag is currently being submitted
    QUEUED = 'queued'

    # Flag is currently being submitted
    PENDING = 'pending'

    # We already submitted this flag and the submission system tells us thats
    DUPLICATE = 'duplicate'

    # something is wrong with our submitter
    ERROR = 'error'

    # the service did not check the flag, but told us to fuck off
    RATELIMIT = 'ratelimit'

    # something is wrong with the submission system
    EXCEPTION = 'exception'

    # we tried to submit our own flag and the submission system lets us know
    OWNFLAG = 'ownflag'

    # the flag is not longer active. This is used if a flags are restricted to a
    # specific time frame
    INACTIVE = 'inactive'

    # flag fits the format and could be sent to the submission system, but the
    # submission system told us it is invalid
    INVALID = 'invalid'

    # This status code is used in case the scoring system requires the services to
    # be working. Flags that are rejected might be sent again!
    SERVICEBROKEN = 'servicebroken'
"""


# Config for framework
ROUND_TIME = 120

# format: regex, group where group 0 means the whole regex
FLAG_REGEX = r"[A-Z0-9]{31}=", 0

FLAG_BATCHSIZE = 100

FLAG_RATELIMIT = 0.5  # Wait in seconds between each call of submit_flags()

START_TIME = 1652529600 # Sat May 14 2022 14:00:00 GMT+0200 (Central European Summer Time)

TEAM_TOKEN = '35888f39d94ce75c3748f09b43ccd215'
SUBMIT_URL = 'http://10.1.0.2:8080/flags'
FLAGID_URL = 'http://10.1.0.2:8081/flagIds'


# End config

def get_services():
    return ['SaaS']


def get_targets():
    flag_ids = requests.get(FLAGID_URL).json()

    targets = {
        service: [
            {
                'ip': ip,
                'extra': json.dumps(ip_info),
            }
            for ip, ip_info in service_info.items()
        ]
        for service, service_info in flag_ids.items()
    }

    return targets


logger = logging.getLogger()


def submit_flags(flags):
    resp = requests.put(SUBMIT_URL, headers={
        'X-Team-Token': TEAM_TOKEN
    }, json=flags).json()

    results = []
    for flag_resp in resp:
        msg = flag_resp['msg']
        if flag_resp['status']:
            status = FlagStatus.OK
        elif 'invalid flag' in msg:
            status = FlagStatus.INVALID
        elif 'flag from nop team' in msg:
            status = FlagStatus.INACTIVE
        elif 'flag is your own' in msg:
            status = FlagStatus.OWNFLAG
        elif 'flag is too old' in msg:
            status = FlagStatus.INACTIVE
        elif 'flag already claimed' in msg:
            status = FlagStatus.DUPLICATE
        else:
            status = FlagStatus.ERROR
        results.append(status)

    return results


if __name__ == '__main__':
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    pp.pprint(get_targets())
    pp.pprint(submit_flags([
        'test_flag_1',
        'test_flag_2',
    ]))