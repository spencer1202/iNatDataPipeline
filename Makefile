TEST_DIR = "tests"
PYTHON_COMMAND = python3
PIP_COMMAND = pip3

init:
	$(PYTHON_COMMAND) -m venv .venv
	source ./.venv/bin/activate
	$(PIP_COMMAND) install -r requirements.txt

test:
	python -m pytest -s

