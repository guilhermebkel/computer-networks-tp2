run:
	python3 roteador.py $(port)

test:
	python3 -m pytest test_integration.py -v -p no:warnings
