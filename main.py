import logging
import os

import dotenv

dotenv.load_dotenv()

LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')


## setup logging
log_level = getattr(logging, LOG_LEVEL)  # maps the string name to the corresponding logging level constant
logging.basicConfig(
    level=log_level,
    format='[%(asctime)s] %(levelname)s [%(module)s-%(funcName)s()::%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S',
)
log = logging.getLogger(__name__)


## manager function -------------------------------------------------
def main() -> None:
    """
    Parses CLI argument and runs the named action if allowed; otherwise logs an invalid message.
    """

    return None


if __name__ == '__main__':
    main()
