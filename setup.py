from setuptools import setup, find_packages

setup(
    name="fantasy-sports-api-2026",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        'Flask>=2.3.0',
        'requests>=2.31.0',
        'python-dotenv>=1.0.0',
    ],
    author="Your Name",
    description="Fantasy Sports API - February 2026 Edition",
    python_requires='>=3.11',
)
