"""
Django settings for sales_portal project.
"""

import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent

# безопасная загрузка .env
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

CSI_API_MODE = os.getenv("CSI_API_MODE", "prod")
CSI_API_BASE = os.getenv("CSI_API_BASE_PROD") if CSI_API_MODE == "prod" else os.getenv("CSI_API_BASE_LOCAL")
CSI_HTTP_TIMEOUT = float(os.getenv("CSI_HTTP_TIMEOUT", "6"))
CSI_CACHE_SECONDS = int(os.getenv("CSI_CACHE_SECONDS", "60"))

CSI = {
    "MODE": CSI_API_MODE,
    "BASE": CSI_API_BASE,
    "HTTP_TIMEOUT": CSI_HTTP_TIMEOUT,
    "CACHE_SECONDS": CSI_CACHE_SECONDS,
    "TOKEN": os.getenv("CSI_API_TOKEN", ""),
}

# Простой локальный кэш (на проде можно поменять на Redis)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "salesportal-cache",
        "TIMEOUT": CSI_CACHE_SECONDS,
        "KEY_FUNCTION": "sales.cache.make_key",
    }
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO"},
        "sales": {"handlers": ["console"], "level": "DEBUG"},
        "requests": {"handlers": ["console"], "level": "WARNING"},
    },
}

# Quick-start development settings - unsuitable for production
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-#zl=j@4t*mj1s^hy*o5nb@+jbg_od^=+bq25)jd%a)_jb6z@1y"
)

DEBUG = os.getenv("DEBUG", "1") == "1"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",") if not DEBUG else []

# ── Куки: политика для локальной разработки и прод ────────────────────────────
# SameSite=Lax нужен для работы сессии между localhost:3000 и localhost:8001
CSRF_COOKIE_NAME = "csrftoken"
CSRF_COOKIE_HTTPONLY = False  # фронту нужно читать cookie
CSRF_COOKIE_SAMESITE = "Lax"  # оставим Lax для localhost
# если у вас dev без https:
CSRF_COOKIE_SECURE = False

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = False

# Безопасные флаги: в dev — False, на проде — True
if DEBUG:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    # SECURE_SSL_REDIRECT = False
else:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # SECURE_SSL_REDIRECT = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "rest_framework",
    "corsheaders",
    'sales.apps.SalesConfig',   # <- не просто 'sales'
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# CORS
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-language",
    "content-type",
    "x-csrftoken",
    "x-requested-with",
    "authorization",
]

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:3000",
    "http://localhost:3000",
]

ROOT_URLCONF = 'sales_portal.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# TEMPLATES
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]

WSGI_APPLICATION = 'sales_portal.wsgi.application'

# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "sales_portal.sqlite3",
    },
    # "legacy": {...}
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024  # 20 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Europe/Madrid'
USE_I18N = True
USE_TZ = True

# Static / Media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

load_dotenv(os.path.join(BASE_DIR, '..', '.env'))

def _clean(s):
    if s is None:
        return None
    return s.replace('\u00a0','').strip()

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = _clean(os.environ.get("EMAIL_HOST", "smtp.gmail.com"))
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS","true").lower() == "true"

EMAIL_HOST_USER = _clean(os.environ.get("EMAIL_HOST_USER"))
EMAIL_HOST_PASSWORD = _clean(os.environ.get("EMAIL_HOST_PASSWORD"))

DEFAULT_FROM_EMAIL = f'{os.environ.get("EMAIL_FROM_NAME","SalesPortal")} <{EMAIL_HOST_USER}>'
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_SUBJECT_PREFIX = "[SalesPortal] "
