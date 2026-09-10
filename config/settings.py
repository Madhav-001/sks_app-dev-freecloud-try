"""Django settings for config project."""

import os
import cloudinary
import dj_database_url
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


cloudinary_config = {
    'cloud_name': os.getenv('CLOUDINARY_CLOUD_NAME'),
    'api_key': os.getenv('CLOUDINARY_API_KEY'),
    'api_secret': os.getenv('CLOUDINARY_API_SECRET'),
    'secure': True,
}
api_proxy = os.getenv('CLOUDINARY_API_PROXY') or os.getenv('CLOUDINARY_PROXY')
if api_proxy:
    cloudinary_config['api_proxy'] = api_proxy

cloudinary.config(**cloudinary_config)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-CHANGE_ME_TO_SOMETHING_LONGER_THAN_32_BYTES"
DEBUG = True
ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "mady21.pythonanywhere.com",
    "sri-kumaran-steels.web.app",
    "sri-kumaran-steels.firebaseapp.com",
    "sks-admin.vercel.app",
    "*",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://sri-kumaran-steels.web.app",
    "https://sri-kumaran-steels.firebaseapp.com",
    "https://sks-admin.vercel.app",
]

CORS_ALLOW_CREDENTIALS = True

# Also allow common headers and methods
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]



AUTH_USER_MODEL = "users.Employee"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

INSTALLED_APPS = [
    'corsheaders', 
    'cloudinary_storage',
    'django.contrib.staticfiles',
    'cloudinary',

    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",

    "users",
    "dealers",
    "tracking",
    "sales",
    "crm",
    "communication",
    "storages",
    "notifications",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "error_logger.ErrorLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

if DATABASES["default"].get("ENGINE") == "django.db.backends.sqlite3":
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["timeout"] = 30


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# TIME_ZONE = "UTC"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# STATIC_URL = "static/"
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static'

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "users.permissions.MustChangePasswordPermission",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SKS Backend System API",
    "DESCRIPTION": "Production-ready API for field employee tracking, sales management, and CRM.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=3),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# Cloudinary Storage Configuration
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME'),
    'API_KEY': os.getenv('CLOUDINARY_API_KEY'),
    'API_SECRET': os.getenv('CLOUDINARY_API_SECRET'),
}
# Keep only non-empty credentials so CLOUDINARY_URL in .env works automatically
CLOUDINARY_STORAGE = {k: v for k, v in CLOUDINARY_STORAGE.items() if v}

STORAGES = {
    "default": {
        "BACKEND": "cloudinary_storage.storage.MediaCloudinaryStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

