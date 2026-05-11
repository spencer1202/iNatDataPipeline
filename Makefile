TEST_DIR = "tests"

init:
	pip install -r requirements.txt

test:
	python -m pytest -s