"""Database package.

Models are imported explicitly by the code that needs them.  Keeping this
package import-light avoids opening a database connection at import time.
"""
