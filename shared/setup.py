from setuptools import setup, find_packages

setup(
    name="shared",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.7.0",
        "pydantic-settings>=2.2.0",
        "sqlalchemy[asyncio]>=2.0.0",
        "asyncpg>=0.29.0",
        "redis>=5.0.0",
        "minio>=7.2.0",
        "pyyaml>=6.0",
        "PyPDF2>=3.0.0",
        "httpx>=0.27.0",
        "google-genai>=1.0.0",
    ],
)
