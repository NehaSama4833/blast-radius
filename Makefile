.PHONY: test bench-dev bench
test:
	pytest backend/tests -q
bench-dev:
	python -m bench.run --split dev --condition graph-rules
# the final held-out run; refuses to run without --final. Do this once, after prompts are frozen.
bench:
	python -m bench.run --split test --condition graph-rules --final
