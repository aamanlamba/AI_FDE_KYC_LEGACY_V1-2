.PHONY: install run test sanity preflight smoke verify
install:
	python -m pip install -r requirements.txt
run:
	python -m uvicorn src.app:app --host 0.0.0.0 --port 8000
test:
	python -m pytest -q
sanity:
	python scripts/sanity_check.py
preflight:
	python scripts/workshop_preflight.py
smoke:
	python scripts/smoke_server.py
verify: preflight sanity test smoke
