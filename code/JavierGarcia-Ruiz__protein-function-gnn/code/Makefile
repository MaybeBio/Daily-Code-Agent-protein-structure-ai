.PHONY: all data train evaluate figures test clean

all: test train figures

data:
	python scripts/download_data.py

train:
	python scripts/train.py

figures:
	python scripts/make_figures.py

test:
	python -m pytest -v tests/

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache/

