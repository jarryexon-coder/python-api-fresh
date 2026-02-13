.PHONY: install run test clean seed dev prod cache-clear docker-build docker-up docker-down update-rosters

# Variables
PYTHON = python
PIP = pip
FLASK_ENV ?= production
DOCKER_COMPOSE = docker-compose
SPORT ?= nba
SEASON ?= 2026
YEAR ?= 2026

install:
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

run:
	$(PYTHON) app.py

dev:
	FLASK_ENV=development $(PYTHON) app.py

prod:
	gunicorn --bind 0.0.0.0:5000 wsgi:app

test:
	pytest tests/ -v --cov=src --cov-report=term --cov-report=html

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.pyd" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -delete
	find . -type f -name ".coverage" -delete
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name "build" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +

seed:
	$(PYTHON) scripts/seed_data.py --year=$(YEAR)

cache-clear:
	$(PYTHON) scripts/clear_cache.py

docker-build:
	$(DOCKER_COMPOSE) build

docker-up:
	$(DOCKER_COMPOSE) up -d

docker-down:
	$(DOCKER_COMPOSE) down

update-rosters:
	$(PYTHON) scripts/update_rosters.py --sport=$(SPORT) --season=$(SEASON)

# Additional helpful commands
lint:
	flake8 src/ tests/
	pylint src/ tests/

format:
	black src/ tests/
	isort src/ tests/

type-check:
	mypy src/

db-init:
	$(PYTHON) scripts/init_db.py

db-migrate:
	$(PYTHON) scripts/migrate_db.py

logs:
	$(DOCKER_COMPOSE) logs -f

shell:
	$(PYTHON) manage.py shell

# Show available commands
help:
	@echo "Available commands:"
	@echo "  make install       - Install dependencies"
	@echo "  make run          - Run application"
	@echo "  make dev          - Run in development mode"
	@echo "  make prod         - Run in production mode (gunicorn)"
	@echo "  make test         - Run tests with coverage"
	@echo "  make clean        - Clean cache files"
	@echo "  make seed YEAR=2026 - Seed database"
	@echo "  make cache-clear  - Clear cache"
	@echo "  make docker-build - Build Docker images"
	@echo "  make docker-up    - Start Docker containers"
	@echo "  make docker-down  - Stop Docker containers"
	@echo "  make update-rosters SPORT=nba SEASON=2026 - Update rosters"
	@echo "  make lint         - Run linters"
	@echo "  make format       - Format code"
	@echo "  make type-check   - Run type checker"
	@echo "  make db-init      - Initialize database"
	@echo "  make db-migrate   - Run migrations"
	@echo "  make logs         - View Docker logs"
	@echo "  make shell        - Open Python shell"
	@echo "  make help         - Show this help message"
