"""
error_logger.py
===============
Local Error Logger for SKS Backend System.

Features:
1. log_error(): Standalone function to log any error/exception to errors.log with time, date, and proper space formatting.
2. ErrorLoggingMiddleware: Automatically intercepts any unhandled 500 exception across all API views and logs it.
3. Formatted with aligned key-value pairs, clear visual delimiters, request context, and full stack trace.
"""

import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

# Resolve base directory
try:
    from django.conf import settings
    BASE_DIR = getattr(settings, "BASE_DIR", Path(__file__).resolve().parent)
except Exception:
    BASE_DIR = Path(__file__).resolve().parent

LOG_FILE_PATH = Path(BASE_DIR) / "errors.log"
_file_lock = threading.Lock()


def _get_client_ip(request) -> str:
    """Extract real client IP address from Django request."""
    if not request:
        return "N/A"
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "Unknown")


def _get_user_info(request) -> str:
    """Extract authenticated user info safely without raising exceptions."""
    if not request:
        return "N/A (No Request Context)"
    try:
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            user_id = getattr(user, "employeeidnum", getattr(user, "id", "Unknown"))
            role_name = getattr(user.role, "name", "No Role") if getattr(user, "role", None) else "No Role"
            return f"{user.username} (ID: {user_id}, Role: {role_name})"
        return "AnonymousUser"
    except Exception:
        return "Unknown User"


def format_error_entry(
    error=None,
    message=None,
    request=None,
    extra=None,
    level: str = "ERROR",
) -> str:
    """
    Constructs a beautifully aligned, space-formatted log entry.
    """
    # 1. Resolve Timestamp
    try:
        from django.utils import timezone
        now = timezone.localtime(timezone.now())
        timestamp_str = now.strftime("%d-%b-%Y %I:%M:%S %p %Z").strip()
    except Exception:
        now = datetime.now()
        timestamp_str = now.strftime("%d-%b-%Y %I:%M:%S %p")

    # 2. Resolve Exception & Traceback
    exc_type, exc_val, exc_tb = sys.exc_info()
    if error is not None and isinstance(error, BaseException):
        exc_val = error
        exc_type = type(error)
        if not exc_tb:
            exc_tb = error.__traceback__

    exception_name = f"{exc_type.__name__}: {exc_val}" if exc_type and exc_val else (str(error) if error else "None")

    if exc_tb:
        tb_str = "".join(traceback.format_exception(exc_type, exc_val, exc_tb)).strip()
    elif error and isinstance(error, BaseException) and getattr(error, "__traceback__", None):
        tb_str = "".join(traceback.format_tb(error.__traceback__)).strip()
    else:
        tb_str = "No traceback available."

    # 3. Build Formatted String
    separator_major = "=" * 90
    separator_minor = "-" * 90

    lines = [
        "",
        separator_major,
        f"  [SKS BACKEND ERROR LOG ENTRY] - {level.upper()}",
        separator_minor,
        f"  DATE & TIME   : {timestamp_str}",
        f"  LOG LEVEL     : {level.upper()}",
    ]

    if message:
        lines.append(f"  MESSAGE       : {message}")

    if exception_name and exception_name != "None":
        lines.append(f"  EXCEPTION     : {exception_name}")

    # Request Context (if available)
    if request:
        lines.extend([
            "",
            "  --- HTTP REQUEST CONTEXT ---",
            f"  ENDPOINT      : {request.method} {request.get_full_path() if hasattr(request, 'get_full_path') else getattr(request, 'path', 'N/A')}",
            f"  CLIENT IP     : {_get_client_ip(request)}",
            f"  USER          : {_get_user_info(request)}",
            f"  CONTENT TYPE  : {request.content_type if hasattr(request, 'content_type') else request.META.get('CONTENT_TYPE', 'N/A')}",
            f"  USER AGENT    : {request.META.get('HTTP_USER_AGENT', 'N/A')}",
        ])

    # Extra Context Dictionary (if provided)
    if extra and isinstance(extra, dict):
        lines.extend([
            "",
            "  --- ADDITIONAL CONTEXT ---",
        ])
        for k, v in extra.items():
            lines.append(f"  {str(k).upper():<14}: {v}")

    # Traceback Section
    lines.extend([
        "",
        "  --- STACK TRACEBACK ---",
        "\n".join(f"  {tb_line}" for tb_line in tb_str.splitlines()),
        separator_major,
        "",
    ])

    return "\n".join(lines)


def log_error(
    error=None,
    message=None,
    request=None,
    extra=None,
    level: str = "ERROR",
    file_path: Path = None,
) -> str:
    """
    Main function to record an error into errors.log locally.

    Parameters:
    - error      : Exception object or error string (optional if called within except block).
    - message    : Human-readable context message describing where/why the error occurred.
    - request    : Django HttpRequest object (optional, extracts user, method, IP, path).
    - extra      : Dict of extra variables or parameters to record (optional).
    - level      : "ERROR", "CRITICAL", or "WARNING" (default: "ERROR").
    - file_path  : Custom log file destination (default: BASE_DIR / 'errors.log').

    Returns:
    - Formatted string written to the file.
    """
    target_path = file_path or LOG_FILE_PATH
    entry = format_error_entry(
        error=error,
        message=message,
        request=request,
        extra=extra,
        level=level,
    )

    try:
        with _file_lock:
            # Ensure directory exists if path contains subdirectories
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
    except Exception as write_err:
        # Fallback to standard error console so error is never silently swallowed
        sys.stderr.write(f"\n[ErrorLogger Failure] Could not write to {target_path}: {write_err}\n")
        sys.stderr.write(entry + "\n")

    return entry


class ErrorLoggingMiddleware:
    """
    Django Middleware that intercepts any unhandled 500 exceptions
    in the request-response lifecycle and automatically writes them to errors.log.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Called by Django when a view raises an uncaught exception."""
        log_error(
            error=exception,
            message="Unhandled 500 Server Exception in View",
            request=request,
            level="ERROR",
        )
        # Return None so Django continues standard exception/500 handler
        return None
