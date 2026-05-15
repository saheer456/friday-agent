"""
backend/__init__.py
Makes the backend directory a Python package, enabling relative imports.
"""
import logging
import sys
from pathlib import Path

# Setup global logging
log_file = Path(__file__).resolve().parent.parent / "logs" / "friday.log"
log_file.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(log_file),
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class StreamToLogger(object):
    """Fake file-like stream object that redirects writes to a logger and the original stream."""
    def __init__(self, logger, log_level=logging.INFO, original_stream=None):
        self.logger = logger
        self.log_level = log_level
        self.original_stream = original_stream

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())
        if self.original_stream:
            try:
                self.original_stream.write(buf)
            except UnicodeEncodeError:
                self.original_stream.write(buf.encode('ascii', 'replace').decode('ascii'))
            self.original_stream.flush()

    def flush(self):
        if self.original_stream:
            self.original_stream.flush()

    def isatty(self):
        return False

# Redirect stdout and stderr, keeping original streams so console still works
sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO, sys.stdout)
sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR, sys.stderr)
