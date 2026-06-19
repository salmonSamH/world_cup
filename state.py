import threading

# Shared cache — background thread writes, callbacks read
cache = {"standings_rows": None, "fixtures": None, "first_upcoming": None, "last_updated": None} #"first_upcoming": None,
cache_lock = threading.Lock()