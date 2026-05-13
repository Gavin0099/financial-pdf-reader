import os
from dotenv import load_dotenv

load_dotenv()


class MongoConfig:
    DATABASE_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("MONGODB_DB_NAME", "financial_pdf_reader")


class AnthropicConfig:
    API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")


class StorageConfig:
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./data/raw_pdfs")
    EXTRACTED_DIR: str = os.getenv("EXTRACTED_DIR", "./data/extracted")
    REPORTS_DIR: str = os.getenv("REPORTS_DIR", "./data/reports")


class AuthConfig:
    JWT_SECRET: str = os.getenv("JWT_SECRET", "change-me")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
