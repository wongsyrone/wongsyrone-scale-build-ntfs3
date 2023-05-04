import collections
import logging
import os
import threading

from .paths import LOG_DIR


def get_logger(logger_name, logger_path, mode='a+'):
    logger = logging.getLogger(logger_name)
    logger.propagate = False
    logger.setLevel('DEBUG')
    logger.handlers = []
    logger.addHandler(logging.FileHandler(os.path.join(LOG_DIR, logger_path), mode))
    return logger


class LoggingContext:

    CONTEXTS = collections.defaultdict(list)

    def __init__(self, path, mode='a+'):
        self.path = f'{path}.log'
        self.mode = mode

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @staticmethod
    def has_handler():
        return False

    @staticmethod
    def handler():
        return LoggingContext.CONTEXTS[threading.current_thread().name][-1]


class ConsoleFilter(logging.Filter):

    def filter(self, record):
        return not LoggingContext.has_handler()


class LogHandler(logging.NullHandler):

    def handle(self, record):
        rv = LoggingContext.has_handler()
        if rv:
            return LoggingContext.handler().handle(record)
        return rv
