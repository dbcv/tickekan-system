#!/virtual/mi4bkdfk6b/public_html/gekidanshirochan.com/tickekan-system/venv/bin/python

import sys
import traceback

import sys, os


from app import app
from wsgiref.handlers import CGIHandler

def application(environ, start_response):
    try:
        return app(environ, start_response)
    except Exception:
        start_response(
            '500 Internal Server Error',
            [('Content-Type', 'text/html; charset=utf-8')]
        )
        return [f"<pre>{traceback.format_exc()}</pre>".encode("utf-8")]

CGIHandler().run(application)