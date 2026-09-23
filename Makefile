.PHONY: test lint demo scenarios clean

test:
	python3 -m unittest discover -s tests -v

lint:
	ruff check handoff tests

demo:
	python3 -m handoff.cli demo

scenarios:
	python3 -m handoff.cli scenarios --dir evals/scenarios

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
