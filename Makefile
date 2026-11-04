.PHONY: install seed test eval demo clean

install:
	pip install --upgrade pip
	pip install -r requirements.txt

seed:
	python -m core.seed

test:
	pytest -v

eval:
	python eval/run_matching_eval.py
	python eval/run_injection_eval.py

demo:
	streamlit run app/Home.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
