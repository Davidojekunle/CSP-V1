.PHONY: help install install-dev test lint format clean docker-build docker-up docker-down migrate shell

help:
@echo "Available commands:"
@echo "  make install        - Install production dependencies"
@echo "  make install-dev    - Install development dependencies"
@echo "  make test           - Run tests"
@echo "  make lint           - Run linting"
@echo "  make format         - Format code"
@echo "  make clean          - Clean temporary files"
@echo "  make docker-build   - Build Docker images"
@echo "  make docker-up      - Start Docker containers"
@echo "  make docker-down    - Stop Docker containers"
@echo "  make migrate        - Run database migrations"
@echo "  make shell          - Open shell in container"

install:
pip install -r requirements.txt

install-dev:
pip install -r requirements-dev.txt

test:
pytest -v --cov=app tests/

lint:
flake8 app tests
mypy app

format:
black app tests
isort app tests

clean:
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
find . -type f -name "*.pyo" -delete
find . -type f -name "*.log" -delete
rm -rf .pytest_cache .mypy_cache .coverage htmlcov

docker-build:
docker-compose build

docker-up:
docker-compose up -d

docker-down:
docker-compose down

migrate:
docker-compose exec api alembic upgrade head

shell:
docker-compose exec api bash

logs:
docker-compose logs -f api
