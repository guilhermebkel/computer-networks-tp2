run:
	python3 roteador.py $(port)

test:
	python3 -m unittest test_integration -v
